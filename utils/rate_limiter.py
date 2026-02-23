"""Rate limiting utilities for API calls."""
import asyncio
import time
from typing import Optional


class TokenBucketRateLimiter:
    """Token bucket rate limiter for API calls.

    Allows a certain number of requests per second with burst capacity.
    """

    def __init__(self, rate: float, capacity: Optional[float] = None):
        """Initialize rate limiter.

        Args:
            rate: Requests per second allowed
            capacity: Maximum burst capacity (defaults to rate * 2)
        """
        self.rate = rate
        self.capacity = capacity if capacity is not None else rate * 2
        self.tokens = self.capacity
        self.last_update = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> bool:
        """Acquire tokens for a request.

        Args:
            tokens: Number of tokens to acquire (default 1.0)

        Returns:
            True if tokens were acquired, False if rate limited
        """
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update

            # Add tokens based on elapsed time
            self.tokens = min(
                self.capacity,
                self.tokens + elapsed * self.rate
            )
            self.last_update = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    async def wait(self, tokens: float = 1.0) -> None:
        """Wait until tokens are available.

        Args:
            tokens: Number of tokens to wait for
        """
        while not await self.acquire(tokens):
            # Calculate wait time
            wait_time = (tokens - self.tokens) / self.rate
            await asyncio.sleep(max(0.01, wait_time))


class ExponentialBackoff:
    """Exponential backoff for retrying failed requests."""

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        multiplier: float = 2.0,
        max_retries: int = 5
    ):
        """Initialize exponential backoff.

        Args:
            initial_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            multiplier: Multiplier for each retry
            max_retries: Maximum number of retries
        """
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.max_retries = max_retries

    async def retry(self, func, *args, **kwargs):
        """Retry a function with exponential backoff.

        Args:
            func: Async function to retry
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result of func

        Raises:
            Exception: If all retries are exhausted
        """
        delay = self.initial_delay
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_exception = e

                # Check if it's a rate limit error
                is_rate_limit = (
                    "rate limit" in str(e).lower() or
                    "429" in str(e) or
                    (hasattr(e, "status") and e.status == 429)
                )

                if attempt < self.max_retries - 1:
                    if is_rate_limit:
                        # Use longer delay for rate limits
                        delay = min(self.max_delay, delay * self.multiplier * 2)
                    else:
                        delay = min(self.max_delay, delay * self.multiplier)

                    await asyncio.sleep(delay)
                else:
                    break

        raise last_exception


class RetryableRequest:
    """Async context manager that retries the full request+status-check cycle."""

    def __init__(self, rate_limiter, backoff, session_method, args, kwargs):
        self.rate_limiter = rate_limiter
        self.backoff = backoff
        self.session_method = session_method
        self.args = args
        self.kwargs = kwargs
        self._response = None

    async def __aenter__(self):
        async def _do_request():
            await self.rate_limiter.wait()
            resp = await self.session_method(*self.args, **self.kwargs).__aenter__()
            try:
                resp.raise_for_status()
                return resp
            except Exception:
                await resp.__aexit__(None, None, None)
                raise

        self._response = await self.backoff.retry(_do_request)
        return self._response

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._response is not None:
            await self._response.__aexit__(exc_type, exc_val, exc_tb)
        return False


class RateLimitedSession:
    """Wrapper for aiohttp session with rate limiting."""

    def __init__(self, rate_limiter: TokenBucketRateLimiter):
        """Initialize rate-limited session.

        Args:
            rate_limiter: Token bucket rate limiter instance
        """
        self.rate_limiter = rate_limiter
        self.backoff = ExponentialBackoff()

    def get(self, session, *args, **kwargs):
        """Rate-limited GET request. Returns an async context manager.

        Args:
            session: aiohttp ClientSession
            *args: Arguments for session.get()
            **kwargs: Keyword arguments for session.get()

        Returns:
            RetryableRequest async context manager
        """
        return RetryableRequest(
            self.rate_limiter, self.backoff, session.get, args, kwargs
        )

    def post(self, session, *args, **kwargs):
        """Rate-limited POST request. Returns an async context manager.

        Args:
            session: aiohttp ClientSession
            *args: Arguments for session.post()
            **kwargs: Keyword arguments for session.post()

        Returns:
            RetryableRequest async context manager
        """
        return RetryableRequest(
            self.rate_limiter, self.backoff, session.post, args, kwargs
        )

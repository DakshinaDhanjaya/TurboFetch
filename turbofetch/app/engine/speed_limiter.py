import asyncio
import time
from typing import Dict


class TokenBucket:
    def __init__(self, rate: float = 0.0, capacity: float = 0.0) -> None:
        self._rate = max(0.0, rate)
        self._capacity = capacity if capacity > 0 else max(65536.0, self._rate)
        self._tokens = self._capacity
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def is_limited(self) -> bool:
        return self._rate > 0

    @property
    def rate(self) -> float:
        return self._rate

    def set_rate(self, rate: float) -> None:
        self._rate = max(0.0, rate)
        if self._rate > 0:
            self._capacity = max(65536.0, self._rate)
            self._tokens = min(self._tokens, self._capacity)
        self._last_update = time.monotonic()

    def set_unlimited(self) -> None:
        self._rate = 0.0
        self._last_update = time.monotonic()

    async def consume(self, amount: int) -> None:
        if amount <= 0 or not self.is_limited:
            return
        remaining = float(amount)
        while remaining > 0:
            sleep_time = 0.0
            async with self._lock:
                if not self.is_limited:
                    return
                now = time.monotonic()
                elapsed = now - self._last_update
                self._last_update = now
                self._tokens = min(
                    self._capacity,
                    self._tokens + elapsed * self._rate,
                )
                take = min(remaining, self._capacity)
                if self._tokens >= take:
                    self._tokens -= take
                    remaining -= take
                else:
                    deficit = take - self._tokens
                    sleep_time = deficit / self._rate
                    self._tokens = 0.0
                    remaining -= take - deficit
            if sleep_time > 0:
                await asyncio.sleep(min(sleep_time, 0.5))


class SpeedLimiter:
    def __init__(self, global_limit: float = 0.0) -> None:
        self._global_bucket = TokenBucket(rate=global_limit)
        self._download_buckets: Dict[str, TokenBucket] = {}

    def set_global_limit(self, bytes_per_sec: float) -> None:
        if bytes_per_sec <= 0:
            self._global_bucket.set_unlimited()
        else:
            self._global_bucket.set_rate(bytes_per_sec)

    def set_download_limit(self, download_id: str, bytes_per_sec: float) -> None:
        if bytes_per_sec <= 0:
            self._download_buckets.pop(download_id, None)
            return
        bucket = self._download_buckets.get(download_id)
        if bucket is None:
            self._download_buckets[download_id] = TokenBucket(rate=bytes_per_sec)
        else:
            bucket.set_rate(bytes_per_sec)

    def remove_download_limit(self, download_id: str) -> None:
        self._download_buckets.pop(download_id, None)

    def get_global_limit(self) -> float:
        return self._global_bucket.rate

    def get_download_limit(self, download_id: str) -> float:
        bucket = self._download_buckets.get(download_id)
        return bucket.rate if bucket else 0.0

    async def acquire(self, download_id: str, amount: int) -> None:
        if amount <= 0:
            return
        if not self._global_bucket.is_limited and not self._download_buckets:
            return
        dl_bucket = self._download_buckets.get(download_id)
        if dl_bucket is not None and dl_bucket.is_limited:
            await dl_bucket.consume(amount)
        if self._global_bucket.is_limited:
            await self._global_bucket.consume(amount)

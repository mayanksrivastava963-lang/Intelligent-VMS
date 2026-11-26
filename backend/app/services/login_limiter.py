"""Shared Redis sign-in throttling with a locked local test fallback."""

import time
from threading import Lock

from redis import Redis, RedisError


class LoginLimiter:
    def __init__(self, redis_url=None):
        self.redis = Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2) if redis_url else None
        self.local = {}
        self.lock = Lock()

    def allow(self, address):
        if self.redis is not None:
            script = """
            local count = redis.call('INCR', KEYS[1])
            if count == 1 then redis.call('EXPIRE', KEYS[1], 60) end
            return count
            """
            try:
                return self.redis.eval(script, 1, "vms:login:" + address) <= 5
            except RedisError:
                raise RuntimeError("Sign-in service is temporarily unavailable") from None
        now = time.monotonic()
        with self.lock:
            for key in list(self.local):
                if self.local[key][1] < now - 60:
                    del self.local[key]
            count, first = self.local.get(address, (0, now))
            if len(self.local) >= 1024 and address not in self.local:
                return False
            self.local[address] = (count + 1, first)
            return count < 5

    def clear(self, address):
        if self.redis is not None:
            try:
                self.redis.delete("vms:login:" + address)
            except RedisError:
                pass
        else:
            with self.lock:
                self.local.pop(address, None)

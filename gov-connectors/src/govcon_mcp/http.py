"""Egress-controlled HTTP client shared by every connector.

Zero-trust properties enforced here (not left to each connector):

* **Deny-by-default egress** - each client is bound to an exact host allowlist
  and HTTPS only. A URL outside it raises before any socket is opened.
* **No redirects** - a 3xx is treated as an error so a compromised or
  misconfigured upstream cannot bounce a request (and its API key) elsewhere.
* **Secrets never leave the client** - credentials are injected at send time,
  stripped from cache keys, and scrubbed from every error message.
* **Bounded everything** - timeouts, response-size cap, JSON-only bodies,
  per-client rate limit, bounded retry with backoff that honours Retry-After.
* **Upstream data is untrusted** - callers receive parsed JSON only; the
  server layer labels it as data, never instructions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx2 as httpx
from pydantic import SecretStr

from .errors import EgressDenied, UpstreamError

log = logging.getLogger("govcon_mcp.http")

USER_AGENT = "govcon-mcp/0.1 (+https://modelcontextprotocol.io)"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class _TokenBucket:
    """Simple async token bucket: ``rate`` requests/second, burst ``capacity``."""

    def __init__(self, rate: float, capacity: int) -> None:
        self.rate, self.capacity = rate, capacity
        self.tokens = float(capacity)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


class _TTLCache:
    """Bounded in-memory LRU with TTL. Only successful responses are cached."""

    def __init__(self, ttl_s: float, max_items: int = 512) -> None:
        self.ttl_s, self.max_items = ttl_s, max_items
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key: str, value: Any) -> None:
        if self.ttl_s <= 0:
            return
        self._data[key] = (time.monotonic() + self.ttl_s, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)


class SafeClient:
    """HTTP client scoped to one upstream service."""

    def __init__(
        self,
        name: str,
        allowed_hosts: set[str] | frozenset[str],
        *,
        secret_params: Mapping[str, SecretStr] | None = None,
        secret_headers: Mapping[str, SecretStr] | None = None,
        rate_per_s: float = 5.0,
        burst: int = 5,
        timeout_s: float = 30.0,
        max_bytes: int = 8 * 1024 * 1024,
        cache_ttl_s: float = 900.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self.allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        self._secret_params = dict(secret_params or {})
        self._secret_headers = dict(secret_headers or {})
        self._max_bytes = max_bytes
        self._max_retries = max_retries
        self._bucket = _TokenBucket(rate_per_s, burst)
        self._cache = _TTLCache(cache_ttl_s)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            transport=transport,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    # -- helpers -----------------------------------------------------------
    def _check_url(self, url: str) -> None:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or host not in self.allowed_hosts or parts.username or parts.password:
            raise EgressDenied(f"{self.name}: egress to {parts.scheme}://{host} is not allowlisted")

    def redact(self, text: str) -> str:
        for secret in (*self._secret_params.values(), *self._secret_headers.values()):
            raw = secret.get_secret_value()
            if raw:
                text = text.replace(raw, "***")
        return text

    @staticmethod
    def _cache_key(method: str, url: str, params: Any, body: Any) -> str:
        return json.dumps([method, url, params, body], sort_keys=True, default=str)

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- public API --------------------------------------------------------
    async def get_json(self, url: str, params: Mapping[str, Any] | list[tuple[str, Any]] | None = None) -> Any:
        return await self._request("GET", url, params=params)

    async def post_json(self, url: str, body: Any, params: Mapping[str, Any] | None = None) -> Any:
        return await self._request("POST", url, params=params, body=body)

    async def _request(self, method: str, url: str, *, params: Any = None, body: Any = None) -> Any:
        self._check_url(url)
        # Normalise params into a list of pairs; drop None so callers can pass optionals freely.
        pairs: list[tuple[str, Any]] = []
        if params:
            items = params.items() if isinstance(params, Mapping) else params
            pairs = [(k, v) for k, v in items if v is not None and v != ""]

        key = self._cache_key(method, url, pairs, body)  # secrets are NOT part of the key
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        send_params = pairs + [(k, v.get_secret_value()) for k, v in self._secret_params.items()]
        headers = {k: v.get_secret_value() for k, v in self._secret_headers.items()}

        attempt = 0
        while True:
            await self._bucket.acquire()
            try:
                data = await self._send_once(method, url, send_params, headers, body)
            except _Retryable as exc:
                attempt += 1
                if attempt > self._max_retries:
                    raise UpstreamError(self.name, exc.status, self.redact(exc.detail)) from None
                delay = exc.retry_after if exc.retry_after is not None else min(30.0, 2 ** attempt)
                delay = min(30.0, delay) + random.uniform(0, 0.5)
                log.warning("%s: retrying after %.1fs (status=%s)", self.name, delay, exc.status)
                await asyncio.sleep(delay)
                continue
            self._cache.put(key, data)
            return data

    async def _send_once(self, method: str, url: str, params: list, headers: dict, body: Any) -> Any:
        try:
            async with self._client.stream(
                method, url, params=params, headers=headers, json=body if body is not None else None
            ) as resp:
                status = resp.status_code
                if 300 <= status < 400:
                    raise UpstreamError(self.name, status, "redirect refused (zero-trust: redirects are not followed)")
                chunks, size = [], 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise UpstreamError(self.name, status, f"response exceeded {self._max_bytes} bytes")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                if status in RETRY_STATUSES:
                    raise _Retryable(status, raw[:300].decode("utf-8", "replace"), _retry_after(resp))
                if status >= 400:
                    raise UpstreamError(self.name, status, self.redact(raw[:500].decode("utf-8", "replace")))
                ctype = resp.headers.get("content-type", "")
                if "json" not in ctype:
                    raise UpstreamError(self.name, status, f"unexpected content-type {ctype!r}")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise _Retryable(0, f"network error: {type(exc).__name__}", None) from None
        try:
            # Defence in depth: some upstreams echo the api_key back in "self" links.
            return json.loads(self.redact(raw.decode("utf-8")))
        except ValueError:
            raise UpstreamError(self.name, status, "invalid JSON from upstream") from None


class _Retryable(Exception):
    def __init__(self, status: int, detail: str, retry_after: float | None) -> None:
        self.status, self.detail, self.retry_after = status, detail, retry_after


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    try:
        return float(value) if value else None
    except ValueError:
        return None

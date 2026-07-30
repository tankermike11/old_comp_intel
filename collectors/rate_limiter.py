"""Shared rate limiter used by every collector (EDGAR, App Store, ...). One
instance per collector run — every request goes through it. Enforces
<=max_rps with a minimum spacing floor, and retries on 429 with the
configured exponential backoff.
"""
import time


class RateLimiter:
    def __init__(self, max_rps=8, min_spacing_ms=120):
        self.min_interval = max(1.0 / max_rps, min_spacing_ms / 1000)
        self._last_call = None

    def wait(self):
        if self._last_call is not None:
            elapsed = time.monotonic() - self._last_call
            remaining = self.min_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last_call = time.monotonic()


def get_with_backoff(client, url, limiter, backoff_seconds, headers=None, params=None):
    """GET through the shared limiter. 403 fails fast (User-Agent problem, don't
    retry blindly). 429 backs off per backoff_seconds, then resumes.
    """
    attempts = [0] + list(backoff_seconds)
    last_resp = None
    for delay in attempts:
        if delay:
            time.sleep(delay)
        limiter.wait()
        resp = client.get(url, headers=headers, params=params)
        if resp.status_code == 403:
            raise PermissionError(
                f"403 from {url} — check required headers/auth for this API (a missing/invalid "
                "User-Agent is the usual cause for SEC EDGAR specifically)"
            )
        if resp.status_code == 429:
            last_resp = resp
            continue
        resp.raise_for_status()
        return resp
    last_resp.raise_for_status()
    return last_resp

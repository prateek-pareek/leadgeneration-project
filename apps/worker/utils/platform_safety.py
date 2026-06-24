"""
Platform safety — circuit breakers, block detection, and per-platform policies.

Prevents hammering LinkedIn, Google, Threads, etc. when they return CAPTCHAs,
rate limits, or auth walls. Opens a circuit to pause requests for a cooldown.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()

# HTTP status codes that indicate blocking
BLOCK_STATUS_CODES = {401, 403, 429, 999}

# Body/title patterns that indicate a block or CAPTCHA page
BLOCK_PATTERNS = [
    r"captcha",
    r"unusual traffic",
    r"verify you(?:'re| are) (?:a )?human",
    r"automated queries",
    r"access denied",
    r"authwall",
    r"checkpoint",
    r"please enable javascript",
    r"rate limit",
    r"too many requests",
    r"temporarily unavailable",
    r"cf-browser-verification",  # Cloudflare
    r"g-recaptcha",
    r"hcaptcha",
]


@dataclass
class PlatformPolicy:
    """Conservative defaults per domain — override via env in scraping.py."""
    requests_per_minute: int = 6
    daily_cap: int = 100
    min_delay_sec: float = 2.0
    max_delay_sec: float = 6.0
    min_scan_interval_sec: int = 1800  # 30 min between full source scans
    snippet_first: bool = True
    max_direct_fetches_per_scan: int = 5
    allow_playwright: bool = False
    circuit_failures_before_open: int = 3
    circuit_open_sec: int = 7200  # 2 hours


PLATFORM_POLICIES: dict[str, PlatformPolicy] = {
    "linkedin.com": PlatformPolicy(
        requests_per_minute=3,
        daily_cap=30,
        min_delay_sec=5.0,
        max_delay_sec=12.0,
        min_scan_interval_sec=3600,
        snippet_first=True,
        max_direct_fetches_per_scan=3,
        allow_playwright=False,
        circuit_failures_before_open=2,
        circuit_open_sec=10800,  # 3 hours
    ),
    "google.com": PlatformPolicy(
        requests_per_minute=4,
        daily_cap=60,
        min_delay_sec=4.0,
        max_delay_sec=10.0,
        min_scan_interval_sec=1800,
        snippet_first=True,
        max_direct_fetches_per_scan=10,
        circuit_failures_before_open=2,
        circuit_open_sec=3600,
    ),
    "threads.net": PlatformPolicy(
        requests_per_minute=4,
        daily_cap=80,
        min_delay_sec=3.0,
        max_delay_sec=8.0,
        snippet_first=True,
        max_direct_fetches_per_scan=5,
        circuit_failures_before_open=3,
    ),
    "nitter": PlatformPolicy(
        requests_per_minute=6,
        daily_cap=150,
        min_delay_sec=2.0,
        max_delay_sec=5.0,
    ),
    "reddit.com": PlatformPolicy(
        requests_per_minute=8,
        daily_cap=250,
        min_delay_sec=1.5,
        max_delay_sec=4.0,
    ),
    "freelancer.com": PlatformPolicy(
        requests_per_minute=10,
        daily_cap=200,
        min_delay_sec=1.0,
        max_delay_sec=2.5,
        snippet_first=True,
        max_direct_fetches_per_scan=30,
    ),
    "upwork.com": PlatformPolicy(
        requests_per_minute=4,
        daily_cap=60,
        min_delay_sec=3.0,
        max_delay_sec=8.0,
        min_scan_interval_sec=3600,
        snippet_first=True,
        max_direct_fetches_per_scan=0,
    ),
    "fiverr.com": PlatformPolicy(
        requests_per_minute=4,
        daily_cap=60,
        min_delay_sec=3.0,
        max_delay_sec=8.0,
        snippet_first=True,
        max_direct_fetches_per_scan=0,
    ),
}


def policy_for(domain: str) -> PlatformPolicy:
    for key, pol in PLATFORM_POLICIES.items():
        if key in domain:
            return pol
    return PlatformPolicy()


def is_blocked(status_code: int | None, body: str = "") -> bool:
    if status_code in BLOCK_STATUS_CODES:
        return True
    if not body:
        return False
    sample = body[:8000].lower()
    return any(re.search(pat, sample) for pat in BLOCK_PATTERNS)


def block_reason(status_code: int | None, body: str = "") -> str:
    if status_code == 429:
        return "rate_limited"
    if status_code == 403:
        return "forbidden"
    if status_code == 999:
        return "linkedin_block"
    if body:
        sample = body[:8000].lower()
        for pat in BLOCK_PATTERNS:
            if re.search(pat, sample):
                return pat.replace(r"(?:'re| are)", "").replace("\\", "")[:40]
    return f"http_{status_code}" if status_code else "unknown_block"


@dataclass
class _CircuitState:
    failures: list[float] = field(default_factory=list)
    open_until: float = 0.0
    last_block_reason: str = ""


class CircuitBreaker:
    """
    Per-domain circuit breaker. After repeated blocks, stops all requests
    to that domain until the cooldown expires.
    """

    def __init__(self):
        self._states: dict[str, _CircuitState] = {}

    def _state(self, domain: str) -> _CircuitState:
        if domain not in self._states:
            self._states[domain] = _CircuitState()
        return self._states[domain]

    def is_open(self, domain: str) -> bool:
        st = self._state(domain)
        if time.monotonic() < st.open_until:
            return True
        if st.open_until and time.monotonic() >= st.open_until:
            st.open_until = 0.0
            st.failures.clear()
            log.info("circuit.closed", domain=domain)
        return False

    def record_success(self, domain: str) -> None:
        st = self._state(domain)
        st.failures.clear()

    def record_failure(self, domain: str, reason: str = "") -> None:
        pol = policy_for(domain)
        st = self._state(domain)
        now = time.monotonic()
        st.failures = [t for t in st.failures if now - t < 900]  # 15 min window
        st.failures.append(now)
        st.last_block_reason = reason or "blocked"

        if len(st.failures) >= pol.circuit_failures_before_open:
            st.open_until = now + pol.circuit_open_sec
            log.error(
                "circuit.opened",
                domain=domain,
                reason=reason,
                cooldown_sec=pol.circuit_open_sec,
                failures=len(st.failures),
            )

    def status(self, domain: str) -> dict:
        st = self._state(domain)
        pol = policy_for(domain)
        return {
            "open": self.is_open(domain),
            "last_block_reason": st.last_block_reason,
            "failures_recent": len(st.failures),
            "cooldown_sec": max(0, int(st.open_until - time.monotonic())),
            "policy": {
                "daily_cap": pol.daily_cap,
                "rpm": pol.requests_per_minute,
                "snippet_first": pol.snippet_first,
            },
        }


circuit_breaker = CircuitBreaker()

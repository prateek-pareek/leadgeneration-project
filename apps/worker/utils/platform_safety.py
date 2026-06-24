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

from utils.scraping_safety import effective_daily_cap, effective_rpm, strict_mode

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
    r"sign in to continue",
    r"login to view",
    r"bot detection",
    r"security check",
]


@dataclass
class PlatformPolicy:
    """Conservative defaults per domain — tightened further when strict mode is on."""
    requests_per_minute: int = 4
    daily_cap: int = 80
    min_delay_sec: float = 2.5
    max_delay_sec: float = 7.0
    min_scan_interval_sec: int = 1800  # 30 min between full source scans
    snippet_first: bool = True
    max_direct_fetches_per_scan: int = 3
    allow_playwright: bool = False
    circuit_failures_before_open: int = 2
    circuit_open_sec: int = 10800  # 3 hours default


PLATFORM_POLICIES: dict[str, PlatformPolicy] = {
    "linkedin.com": PlatformPolicy(
        requests_per_minute=2,
        daily_cap=25,
        min_delay_sec=6.0,
        max_delay_sec=14.0,
        min_scan_interval_sec=7200,
        snippet_first=True,
        max_direct_fetches_per_scan=0,
        allow_playwright=False,
        circuit_failures_before_open=1,
        circuit_open_sec=14400,  # 4 hours
    ),
    "google.com": PlatformPolicy(
        requests_per_minute=3,
        daily_cap=45,
        min_delay_sec=5.0,
        max_delay_sec=12.0,
        min_scan_interval_sec=3600,
        snippet_first=True,
        max_direct_fetches_per_scan=0,
        circuit_failures_before_open=1,
        circuit_open_sec=7200,
    ),
    "threads.net": PlatformPolicy(
        requests_per_minute=2,
        daily_cap=40,
        min_delay_sec=4.0,
        max_delay_sec=10.0,
        min_scan_interval_sec=3600,
        snippet_first=True,
        max_direct_fetches_per_scan=2,
        circuit_failures_before_open=2,
        circuit_open_sec=10800,
    ),
    "nitter": PlatformPolicy(
        requests_per_minute=4,
        daily_cap=80,
        min_delay_sec=3.0,
        max_delay_sec=7.0,
        min_scan_interval_sec=1800,
        circuit_failures_before_open=2,
        circuit_open_sec=7200,
    ),
    "reddit.com": PlatformPolicy(
        requests_per_minute=5,
        daily_cap=120,
        min_delay_sec=2.5,
        max_delay_sec=6.0,
        min_scan_interval_sec=1200,
        circuit_failures_before_open=2,
        circuit_open_sec=5400,
    ),
    "freelancer.com": PlatformPolicy(
        requests_per_minute=6,
        daily_cap=100,
        min_delay_sec=2.0,
        max_delay_sec=5.0,
        snippet_first=True,
        max_direct_fetches_per_scan=20,
        circuit_failures_before_open=3,
    ),
    "upwork.com": PlatformPolicy(
        requests_per_minute=2,
        daily_cap=30,
        min_delay_sec=5.0,
        max_delay_sec=12.0,
        min_scan_interval_sec=7200,
        snippet_first=True,
        max_direct_fetches_per_scan=0,
        circuit_failures_before_open=1,
        circuit_open_sec=14400,
    ),
    "fiverr.com": PlatformPolicy(
        requests_per_minute=2,
        daily_cap=30,
        min_delay_sec=5.0,
        max_delay_sec=12.0,
        snippet_first=True,
        max_direct_fetches_per_scan=0,
        circuit_failures_before_open=1,
    ),
    "guru.com": PlatformPolicy(
        requests_per_minute=2,
        daily_cap=30,
        min_delay_sec=5.0,
        max_delay_sec=12.0,
        snippet_first=True,
        max_direct_fetches_per_scan=0,
    ),
    "peopleperhour.com": PlatformPolicy(
        requests_per_minute=2,
        daily_cap=30,
        min_delay_sec=5.0,
        max_delay_sec=12.0,
        snippet_first=True,
        max_direct_fetches_per_scan=0,
    ),
    "contra.com": PlatformPolicy(
        requests_per_minute=2,
        daily_cap=30,
        min_delay_sec=5.0,
        max_delay_sec=12.0,
        snippet_first=True,
        max_direct_fetches_per_scan=0,
    ),
    "remoteok.com": PlatformPolicy(
        requests_per_minute=8,
        daily_cap=80,
        min_delay_sec=2.0,
        max_delay_sec=5.0,
        min_scan_interval_sec=900,
    ),
    "remotive.com": PlatformPolicy(
        requests_per_minute=8,
        daily_cap=80,
        min_delay_sec=2.0,
        max_delay_sec=5.0,
        min_scan_interval_sec=900,
    ),
    "arbeitnow.com": PlatformPolicy(
        requests_per_minute=8,
        daily_cap=80,
        min_delay_sec=2.0,
        max_delay_sec=5.0,
        min_scan_interval_sec=900,
    ),
    "jobicy.com": PlatformPolicy(
        requests_per_minute=6,
        daily_cap=60,
        min_delay_sec=2.5,
        max_delay_sec=6.0,
        min_scan_interval_sec=900,
    ),
    "workingnomads.com": PlatformPolicy(
        requests_per_minute=6,
        daily_cap=60,
        min_delay_sec=2.5,
        max_delay_sec=6.0,
        min_scan_interval_sec=900,
    ),
    "himalayas.app": PlatformPolicy(
        requests_per_minute=5,
        daily_cap=50,
        min_delay_sec=3.0,
        max_delay_sec=7.0,
        min_scan_interval_sec=1200,
    ),
    "weworkremotely.com": PlatformPolicy(
        requests_per_minute=6,
        daily_cap=60,
        min_delay_sec=2.5,
        max_delay_sec=6.0,
        min_scan_interval_sec=900,
    ),
    "api.github.com": PlatformPolicy(
        requests_per_minute=5,
        daily_cap=60,
        min_delay_sec=2.0,
        max_delay_sec=5.0,
        min_scan_interval_sec=900,
        circuit_failures_before_open=2,
        circuit_open_sec=3600,
    ),
    "dev.to": PlatformPolicy(
        requests_per_minute=10,
        daily_cap=150,
        min_delay_sec=1.5,
        max_delay_sec=4.0,
        min_scan_interval_sec=600,
    ),
    "producthunt.com": PlatformPolicy(
        requests_per_minute=8,
        daily_cap=100,
        min_delay_sec=2.0,
        max_delay_sec=5.0,
        min_scan_interval_sec=900,
    ),
}


def policy_for(domain: str) -> PlatformPolicy:
    for key, pol in PLATFORM_POLICIES.items():
        if key in domain:
            return PlatformPolicy(
                requests_per_minute=effective_rpm(pol.requests_per_minute),
                daily_cap=effective_daily_cap(pol.daily_cap),
                min_delay_sec=pol.min_delay_sec * (1.4 if strict_mode() else 1.0),
                max_delay_sec=pol.max_delay_sec * (1.3 if strict_mode() else 1.0),
                min_scan_interval_sec=int(pol.min_scan_interval_sec * (1.5 if strict_mode() else 1.0)),
                snippet_first=pol.snippet_first,
                max_direct_fetches_per_scan=0 if (strict_mode() and pol.max_direct_fetches_per_scan == 0) else (
                    min(pol.max_direct_fetches_per_scan, 2) if strict_mode() else pol.max_direct_fetches_per_scan
                ),
                allow_playwright=pol.allow_playwright and not strict_mode(),
                circuit_failures_before_open=max(1, pol.circuit_failures_before_open - (1 if strict_mode() else 0)),
                circuit_open_sec=int(pol.circuit_open_sec * (1.25 if strict_mode() else 1.0)),
            )
    base = PlatformPolicy()
    return PlatformPolicy(
        requests_per_minute=effective_rpm(base.requests_per_minute),
        daily_cap=effective_daily_cap(base.daily_cap),
        min_delay_sec=base.min_delay_sec * (1.4 if strict_mode() else 1.0),
        max_delay_sec=base.max_delay_sec * (1.3 if strict_mode() else 1.0),
        min_scan_interval_sec=int(base.min_scan_interval_sec * (1.5 if strict_mode() else 1.0)),
        snippet_first=base.snippet_first,
        max_direct_fetches_per_scan=min(base.max_direct_fetches_per_scan, 2) if strict_mode() else base.max_direct_fetches_per_scan,
        allow_playwright=base.allow_playwright and not strict_mode(),
        circuit_failures_before_open=max(1, base.circuit_failures_before_open - (1 if strict_mode() else 0)),
        circuit_open_sec=int(base.circuit_open_sec * (1.25 if strict_mode() else 1.0)),
    )


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

    def any_open(self, domains: list[str]) -> tuple[bool, str]:
        for d in domains:
            if self.is_open(d):
                st = self.status(d)
                return True, f"{d} paused ({st['last_block_reason']}) — retry in {st['cooldown_sec'] // 60} min"
        return False, ""

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
                strict_mode=strict_mode(),
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
                "strict_mode": strict_mode(),
            },
        }


circuit_breaker = CircuitBreaker()

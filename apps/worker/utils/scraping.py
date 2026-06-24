"""
Responsible scraping utilities for ProspectOS.

Protections implemented:
  1. Per-domain rate limiting  — never exceeds a safe req/min ceiling per domain
  2. Human-like random delays  — jittered sleep between requests (not fixed intervals)
  3. User-Agent rotation       — pool of real browser UA strings, rotated randomly
  4. Robots.txt compliance     — checks and caches robots.txt before crawling
  5. Playwright stealth        — hides automation signals (webdriver flag, plugins, etc.)
  6. Exponential backoff       — retries on 429 / 503 with increasing wait
  7. Daily quota caps          — hard ceiling on requests to each domain per 24h
  8. Deduplication             — tracks already-seen URLs to avoid repeat hits
"""

import asyncio
import random
import time
import urllib.parse
import urllib.robotparser
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

import httpx
import structlog
from playwright.async_api import Page

from utils.platform_safety import circuit_breaker, is_blocked, block_reason, policy_for
from utils.scraping_safety import (
    scan_interval_sec,
    strict_mode,
    effective_rpm,
    effective_daily_cap,
)

log = structlog.get_logger()

# ── User-Agent rotation pool ──────────────────────────────────
# Real Chrome/Firefox UAs from major operating systems.
# Rotate to avoid fingerprinting by static UA string.
UA_POOL = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.86 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    # Safari
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

def random_ua() -> str:
    return random.choice(UA_POOL)


# ── Realistic delay profiles per platform ────────────────────
# (min_sec, max_sec) — sampled from a uniform distribution with
# an extra random spike simulating "reading" or "thinking" time.
DELAY_PROFILES: dict[str, tuple[float, float]] = {
    "linkedin.com":      (4.0, 9.0),
    "threads.net":       (2.0, 5.0),
    "google.com":        (3.0, 7.0),
    "twitter.com":       (2.0, 5.0),
    "nitter":            (1.5, 4.0),
    "reddit.com":        (1.5, 3.5),
    "producthunt.com":   (1.0, 3.0),
    "dev.to":            (0.8, 2.0),
    "remoteok.com":      (1.0, 2.5),
    "remotive.com":      (1.0, 2.5),
    "arbeitnow.com":     (1.0, 2.5),
    "weworkremotely.com":(1.0, 2.5),
    "freelancer.com":    (1.0, 2.5),
    "upwork.com":        (2.0, 5.0),
    "fiverr.com":        (2.0, 5.0),
    "news.ycombinator":  (0.5, 1.5),
    "default":           (1.0, 3.0),
}

def delay_for(domain: str) -> float:
    pol = policy_for(domain)
    lo, hi = pol.min_delay_sec, pol.max_delay_sec
    for key, (plo, phi) in DELAY_PROFILES.items():
        if key in domain:
            lo, hi = max(lo, plo), max(hi, phi)
            break
    base = random.uniform(lo, hi)
    if random.random() < 0.15:
        base += random.uniform(2.0, 5.0)
    return base


async def human_delay(domain: str = "default") -> None:
    """Sleep for a human-like random duration appropriate for the domain."""
    secs = delay_for(domain)
    log.debug("scraping.delay", domain=domain, seconds=round(secs, 2))
    await asyncio.sleep(secs)


# ── Per-domain rate limiter ────────────────────────────────────
class DomainRateLimiter:
    """
    Token-bucket rate limiter per domain.
    Guarantees we never exceed max_per_minute requests to any single domain.
    """

    # Hard ceilings (requests per minute) — tightened in strict mode via policy_for
    LIMITS: dict[str, int] = {
        "linkedin.com":      2,
        "threads.net":       3,
        "google.com":        3,
        "twitter.com":       5,
        "reddit.com":        6,
        "producthunt.com":   8,
        "dev.to":            10,
        "remoteok.com":      8,
        "remotive.com":      8,
        "arbeitnow.com":     8,
        "weworkremotely.com":6,
        "jobicy.com":        5,
        "workingnomads.com": 5,
        "himalayas.app":     4,
        "freelancer.com":    6,
        "api.github.com":    5,
        "upwork.com":        2,
        "fiverr.com":        2,
        "default":           8,
    }

    # Daily quota per domain (total requests in 24h)
    DAILY_CAPS: dict[str, int] = {
        "linkedin.com":      25,
        "threads.net":       40,
        "google.com":        45,
        "twitter.com":       80,
        "reddit.com":        120,
        "producthunt.com":   100,
        "dev.to":            150,
        "remoteok.com":      80,
        "remotive.com":      80,
        "arbeitnow.com":     80,
        "weworkremotely.com":60,
        "jobicy.com":        60,
        "workingnomads.com": 60,
        "himalayas.app":     50,
        "freelancer.com":    100,
        "api.github.com":    60,
        "upwork.com":        30,
        "fiverr.com":        30,
        "default":           120,
    }

    def __init__(self):
        self._last_request: dict[str, float] = defaultdict(float)
        self._daily_count: dict[str, int] = defaultdict(int)
        self._daily_reset: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _ceiling(self, domain: str) -> int:
        for key, val in self.LIMITS.items():
            if key in domain:
                return effective_rpm(val)
        return effective_rpm(self.LIMITS["default"])

    def _daily_cap(self, domain: str) -> int:
        for key, val in self.DAILY_CAPS.items():
            if key in domain:
                return effective_daily_cap(val)
        return effective_daily_cap(self.DAILY_CAPS["default"])

    async def acquire(self, domain: str) -> bool:
        """
        Wait until it's safe to make a request to this domain.
        Returns False if the daily quota is exhausted or circuit is open.
        """
        if circuit_breaker.is_open(domain):
            log.warning("scraping.circuit_open", domain=domain)
            return False

        pol = policy_for(domain)
        now = time.monotonic()
        wall = time.time()

        # Reset daily counter after 24h
        if wall - self._daily_reset[domain] > 86_400:
            self._daily_count[domain] = 0
            self._daily_reset[domain] = wall

        # Check daily cap (policy overrides defaults when stricter)
        cap = min(self._daily_cap(domain), pol.daily_cap)
        if self._daily_count[domain] >= cap:
            log.warning("scraping.daily_cap_hit", domain=domain, cap=cap)
            return False

        # Token-bucket: wait if we're going too fast
        rpm = min(self._ceiling(domain), pol.requests_per_minute)
        min_gap = 60.0 / rpm
        elapsed = now - self._last_request[domain]
        if elapsed < min_gap:
            wait = min_gap - elapsed + random.uniform(0, min_gap * 0.3)  # add jitter
            await asyncio.sleep(wait)

        self._last_request[domain] = time.monotonic()
        self._daily_count[domain] += 1
        return True

    def remaining_today(self, domain: str) -> int:
        cap = self._daily_cap(domain)
        return max(0, cap - self._daily_count[domain])


# Global singleton used by all connectors
rate_limiter = DomainRateLimiter()


# ── Robots.txt compliance ─────────────────────────────────────
_robots_cache: dict[str, tuple[urllib.robotparser.RobotFileParser, float]] = {}
ROBOTS_CACHE_TTL = 3600  # re-fetch after 1 hour

async def can_fetch(url: str, ua: str = "*") -> bool:
    """
    Check robots.txt for the given URL. Caches results for 1h.
    Returns True if allowed (or if robots.txt can't be fetched).
    """
    parsed = urllib.parse.urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{base}/robots.txt"

    now = time.time()
    cached = _robots_cache.get(base)
    if cached and (now - cached[1]) < ROBOTS_CACHE_TTL:
        rp = cached[0]
    else:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(robots_url)
                rp.parse(resp.text.splitlines())
        except Exception:
            # If we can't fetch robots.txt, assume allowed
            return True
        _robots_cache[base] = (rp, now)

    return rp.can_fetch(ua, url)


# ── httpx client with safety defaults ────────────────────────
def safe_client(
    ua: str | None = None,
    extra_headers: dict | None = None,
    timeout: float = 15.0,
) -> httpx.AsyncClient:
    """Create an httpx client with rotating UA and realistic headers."""
    ua = ua or random_ua()
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }
    if extra_headers:
        headers.update(extra_headers)
    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        follow_redirects=True,
        http2=True,
    )


# ── Playwright stealth settings ────────────────────────────────
STEALTH_INIT_SCRIPT = """
() => {
    // Remove webdriver property
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // Spoof plugins (empty in headless)
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });

    // Spoof languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['en-US', 'en'],
    });

    // Spoof hardware concurrency (headless usually returns 2)
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });

    // Spoof device memory
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

    // Override permissions
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);

    // Chrome runtime spoof
    window.chrome = { runtime: {} };

    // Remove automation markers
    delete window.__webdriver_evaluate;
    delete window.__selenium_unwrapped;
    delete window.__fxdriver_evaluate;
    delete window.__driver_evaluate;
}
"""

REALISTIC_VIEWPORT = {"width": 1366, "height": 768}


async def stealth_page(browser) -> Page:
    """
    Create a Playwright page with stealth settings applied:
    - Hides webdriver flag
    - Sets realistic viewport and UA
    - Blocks image/font/media loading (speed + fingerprint reduction)
    - Injects anti-detection JS
    """
    ua = random_ua()
    ctx = await browser.new_context(
        user_agent=ua,
        viewport=REALISTIC_VIEWPORT,
        locale="en-US",
        timezone_id="America/New_York",
        java_script_enabled=True,
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        },
    )

    # Reduce footprint: block media that reveals headless
    await ctx.route(
        "**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,mp4,mp3,webm}",
        lambda r: r.abort(),
    )
    # Block analytics / tracking scripts
    await ctx.route(
        "**/{google-analytics,gtag,mixpanel,segment,hotjar,amplitude}**",
        lambda r: r.abort(),
    )

    page = await ctx.new_page()
    await page.add_init_script(STEALTH_INIT_SCRIPT)
    return page


# ── Retry with exponential backoff ───────────────────────────
async def with_backoff(
    fn: Callable,
    *args,
    max_attempts: int = 3,
    base_delay: float = 2.0,
    domain: str = "",
    **kwargs,
):
    """
    Run an async function with exponential backoff on HTTP errors.
    Records circuit-breaker failures on block responses.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            result = await fn(*args, **kwargs)
            # httpx response — check for soft blocks in 200 body
            if hasattr(result, "status_code"):
                body = ""
                try:
                    body = result.text[:8000] if result.text else ""
                except Exception:
                    pass
                if is_blocked(result.status_code, body):
                    reason = block_reason(result.status_code, body)
                    if domain:
                        circuit_breaker.record_failure(domain, reason)
                    if attempt < max_attempts and result.status_code in (429, 503, 502, 403, 999):
                        wait = base_delay * (2 ** (attempt - 1)) + random.uniform(3, 8)
                        log.warning("scraping.blocked", status=result.status_code, domain=domain, reason=reason, retry_in=round(wait, 1))
                        await asyncio.sleep(wait)
                        continue
                    return None
                if domain:
                    circuit_breaker.record_success(domain)
            return result
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            body = ""
            try:
                body = e.response.text[:8000]
            except Exception:
                pass
            if domain and is_blocked(status, body):
                circuit_breaker.record_failure(domain, block_reason(status, body))
            if status in (429, 503, 502, 403, 999) and attempt < max_attempts:
                wait = base_delay * (2 ** (attempt - 1)) + random.uniform(3, 8)
                log.warning(
                    "scraping.rate_limited",
                    status=status,
                    domain=domain,
                    attempt=attempt,
                    retry_in=round(wait, 1),
                )
                await asyncio.sleep(wait)
            else:
                raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            if attempt < max_attempts:
                wait = base_delay * attempt + random.uniform(1, 3)
                log.warning("scraping.connection_error", error=str(e), retry_in=round(wait, 1))
                await asyncio.sleep(wait)
            else:
                raise
    return None


def scan_allowed(platform_type: str, last_run_at) -> tuple[bool, str]:
    """Check if enough time has passed since last source scan for this platform."""
    if last_run_at is None:
        return True, ""
    interval = scan_interval_sec(platform_type)
    if interval <= 0:
        return True, ""
    try:
        if hasattr(last_run_at, "timestamp"):
            elapsed = time.time() - last_run_at.timestamp()
        else:
            return True, ""
    except Exception:
        return True, ""
    if elapsed < interval:
        wait_min = int((interval - elapsed) / 60) + 1
        hint = " (strict safety mode)" if strict_mode() else ""
        return False, f"Cooldown active{hint} — wait {wait_min} min before scanning {platform_type} again"
    return True, ""


# ── URL deduplication ─────────────────────────────────────────
class SeenURLs:
    """
    In-memory set of URLs we've already scraped this session.
    Prevents hammering the same URL twice in one source scan run.
    """
    def __init__(self):
        self._seen: set[str] = set()

    def check_add(self, url: str) -> bool:
        """Returns True if URL is new (not seen before), and marks it seen."""
        normalized = url.rstrip("/").lower().split("?")[0]
        if normalized in self._seen:
            return False
        self._seen.add(normalized)
        return True

    def __len__(self):
        return len(self._seen)


# ── Convenience: domain extraction ───────────────────────────
def domain_of(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc
    except Exception:
        return url

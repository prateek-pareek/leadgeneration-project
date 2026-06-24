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
    "google.com":        (3.0, 7.0),
    "twitter.com":       (2.0, 5.0),
    "nitter":            (1.5, 4.0),
    "reddit.com":        (1.5, 3.5),
    "producthunt.com":   (1.0, 3.0),
    "dev.to":            (0.8, 2.0),
    "news.ycombinator":  (0.5, 1.5),
    "default":           (1.0, 3.0),
}

def delay_for(domain: str) -> float:
    for key, (lo, hi) in DELAY_PROFILES.items():
        if key in domain:
            base = random.uniform(lo, hi)
            # 15% chance of a longer "reading" pause (simulates human behaviour)
            if random.random() < 0.15:
                base += random.uniform(2.0, 5.0)
            return base
    lo, hi = DELAY_PROFILES["default"]
    return random.uniform(lo, hi)


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

    # Hard ceilings (requests per minute) — intentionally conservative
    LIMITS: dict[str, int] = {
        "linkedin.com":      4,    # very aggressive detection
        "google.com":        6,    # CAPTCHA risk
        "twitter.com":       8,
        "reddit.com":        10,   # Reddit asks for ≤60/min authenticated, much less unauthed
        "producthunt.com":   15,
        "dev.to":            20,
        "default":           12,
    }

    # Daily quota per domain (total requests in 24h)
    DAILY_CAPS: dict[str, int] = {
        "linkedin.com":      50,
        "google.com":        80,
        "twitter.com":       200,
        "reddit.com":        300,
        "producthunt.com":   400,
        "dev.to":            500,
        "default":           300,
    }

    def __init__(self):
        self._last_request: dict[str, float] = defaultdict(float)
        self._daily_count: dict[str, int] = defaultdict(int)
        self._daily_reset: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _ceiling(self, domain: str) -> int:
        for key, val in self.LIMITS.items():
            if key in domain:
                return val
        return self.LIMITS["default"]

    def _daily_cap(self, domain: str) -> int:
        for key, val in self.DAILY_CAPS.items():
            if key in domain:
                return val
        return self.DAILY_CAPS["default"]

    async def acquire(self, domain: str) -> bool:
        """
        Wait until it's safe to make a request to this domain.
        Returns False if the daily quota is exhausted (request should be skipped).
        """
        now = time.monotonic()
        wall = time.time()

        # Reset daily counter after 24h
        if wall - self._daily_reset[domain] > 86_400:
            self._daily_count[domain] = 0
            self._daily_reset[domain] = wall

        # Check daily cap
        cap = self._daily_cap(domain)
        if self._daily_count[domain] >= cap:
            log.warning("scraping.daily_cap_hit", domain=domain, cap=cap)
            return False

        # Token-bucket: wait if we're going too fast
        min_gap = 60.0 / self._ceiling(domain)
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
    Handles 429 (Too Many Requests) and 503 (Service Unavailable).
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in (429, 503, 502) and attempt < max_attempts:
                wait = base_delay * (2 ** (attempt - 1)) + random.uniform(1, 3)
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
                wait = base_delay * attempt + random.uniform(0.5, 2)
                log.warning("scraping.connection_error", error=str(e), retry_in=round(wait, 1))
                await asyncio.sleep(wait)
            else:
                raise
    return None


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

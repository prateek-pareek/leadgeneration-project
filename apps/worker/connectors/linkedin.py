"""
LinkedIn connector — finds public posts via Google Search (snippet-first).

Safety strategy (minimises LinkedIn direct requests):
  1. Google site: search only — primary data source
  2. Use Google snippets when ≥40 chars — ZERO LinkedIn hits
  3. Optional httpx OG-meta fetch — lightweight, no browser
  4. Playwright only if SCRAPING_LINKEDIN_USE_PLAYWRIGHT=true (off by default)
  5. Circuit breaker pauses all LinkedIn/Google requests after blocks
  6. Max 3 direct LinkedIn fetches per scan, 30/day, 3 req/min
  7. 1-hour minimum between LinkedIn source scans
  8. No login, no auth, public content only
"""

import hashlib
import re
from datetime import datetime, timezone

import structlog
from playwright.async_api import async_playwright

from config import settings
from utils.platform_safety import circuit_breaker, is_blocked, policy_for
from utils.scraping import (
    rate_limiter, human_delay, safe_client, stealth_page,
    can_fetch, with_backoff, SeenURLs, random_ua,
)

log = structlog.get_logger()

GOOGLE_URL = "https://www.google.com/search"
SNIPPET_MIN_LEN = 40
INTENT_KEYWORDS = [
    "need help", "looking for", "hire", "find a developer", "build",
    "infrastructure", "cloud", "devops", "struggling with", "can't find",
    "outsource", "managed service", "IT support", "tech team", "CTO",
    "cost too high", "legacy", "migration", "scaling", "security",
]


async def _google_search_linkedin(keywords: list[str], max_results: int) -> list[dict]:
    if circuit_breaker.is_open("google.com"):
        log.warning("linkedin.google_circuit_open")
        return []

    query = f'site:linkedin.com/posts ({" OR ".join(keywords)}) -inurl:company'
    results = []

    ok = await rate_limiter.acquire("google.com")
    if not ok:
        log.warning("linkedin.google_daily_cap")
        return []

    async with safe_client() as client:
        try:
            resp = await with_backoff(
                client.get,
                GOOGLE_URL,
                params={"q": query, "num": min(max_results, 10), "hl": "en", "tbs": "qdr:w"},
                domain="google.com",
                max_attempts=2,
            )
            if resp is None or resp.status_code != 200:
                return []

            html = resp.text
            if is_blocked(resp.status_code, html):
                log.warning("linkedin.google_blocked")
                return []

            pattern = r'/url\?q=(https://(?:www\.)?linkedin\.com/posts/[^&"\']+)'
            urls = list(dict.fromkeys(re.findall(pattern, html)))
            snippet_pattern = r'<span[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</span>'
            snippets = [re.sub(r"<[^>]+>", "", s) for s in re.findall(snippet_pattern, html, re.DOTALL)]

            for i, url in enumerate(urls[:max_results]):
                results.append({
                    "url": url,
                    "snippet": snippets[i].strip() if i < len(snippets) else "",
                })
        except Exception as e:
            log.warning("linkedin.google_failed", error=str(e))

    await human_delay("google.com")
    return results


def _meta_from_html(html: str, prop: str) -> str | None:
    m = re.search(
        rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
        html, re.IGNORECASE,
    )
    if not m:
        m = re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(prop)}["\']',
            html, re.IGNORECASE,
        )
    return m.group(1).strip() if m else None


async def _fetch_og_meta(url: str) -> dict | None:
    """Lightweight httpx fetch for OG tags — no browser fingerprint."""
    if circuit_breaker.is_open("linkedin.com"):
        return None

    ok = await rate_limiter.acquire("linkedin.com")
    if not ok:
        return None

    if not await can_fetch(url, ua=random_ua()):
        return None

    async with safe_client() as client:
        try:
            resp = await with_backoff(client.get, url, domain="linkedin.com", max_attempts=2)
            if resp is None or resp.status_code != 200:
                return None
            if is_blocked(resp.status_code, resp.text):
                return None

            og_desc = _meta_from_html(resp.text, "og:description")
            og_title = _meta_from_html(resp.text, "og:title")
            author_name = None
            if og_title:
                m = re.match(r"^(.+?) (?:on LinkedIn|posted on LinkedIn)", og_title)
                if m:
                    author_name = m.group(1).strip()

            text = og_desc or ""
            if len(text) < 20:
                return None

            return {
                "text": text,
                "author_name": author_name,
                "author_handle": _handle_from_url(url),
                "posted_at": None,
                "fetch_method": "og_meta",
            }
        except Exception as e:
            log.warning("linkedin.og_fetch_error", url=url, error=str(e))
            return None
        finally:
            await human_delay("linkedin.com")


async def _scrape_playwright(url: str) -> dict | None:
    """Last resort — stealth Playwright. Only when explicitly enabled."""
    if not settings.scraping_linkedin_use_playwright:
        return None
    if circuit_breaker.is_open("linkedin.com"):
        return None

    ok = await rate_limiter.acquire("linkedin.com")
    if not ok:
        return None

    if not await can_fetch(url, ua=random_ua()):
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await stealth_page(browser)
            await page.goto(url, wait_until="domcontentloaded", timeout=18000)
            await human_delay("linkedin.com")

            og_desc = await page.evaluate(
                "document.querySelector('meta[property=\"og:description\"]')?.content"
            )
            og_title = await page.evaluate(
                "document.querySelector('meta[property=\"og:title\"]')?.content"
            )

            author_name = None
            if og_title:
                m = re.match(r"^(.+?) (?:on LinkedIn|posted on LinkedIn)", og_title)
                if m:
                    author_name = m.group(1).strip()

            text = og_desc or ""
            if not text or len(text) < 20:
                return None

            return {
                "text": text,
                "author_name": author_name,
                "author_handle": _handle_from_url(url),
                "posted_at": None,
                "fetch_method": "playwright",
            }
        except Exception as e:
            log.warning("linkedin.playwright_error", url=url, error=str(e))
            circuit_breaker.record_failure("linkedin.com", "playwright_error")
            return None
        finally:
            await browser.close()


def _handle_from_url(url: str) -> str:
    m = re.search(r"/posts/([^_/?]+)", url)
    return m.group(1) if m else ""


def _snippet_post(result: dict) -> dict | None:
    snippet = result.get("snippet", "")
    if len(snippet) < SNIPPET_MIN_LEN:
        return None
    url = result["url"]
    return {
        "text": snippet,
        "author_name": None,
        "author_handle": _handle_from_url(url),
        "posted_at": None,
        "fetch_method": "google_snippet",
    }


async def fetch(source_config: dict) -> list[dict]:
    keywords = source_config.get("keywords", [])
    pol = policy_for("linkedin.com")
    max_results = min(source_config.get("max_results", 10), 15)
    max_direct = min(
        settings.scraping_linkedin_max_direct_per_scan,
        pol.max_direct_fetches_per_scan,
    )

    if not keywords:
        return []

    log.info(
        "linkedin.starting",
        keywords=keywords,
        max=max_results,
        snippet_first=pol.snippet_first,
        playwright=settings.scraping_linkedin_use_playwright,
    )

    search_results = await _google_search_linkedin(keywords, max_results)
    seen = SeenURLs()
    posts = []
    direct_fetches = 0

    for result in search_results:
        url = result["url"]
        if not seen.check_add(url):
            continue

        post_data = None

        # Tier 1: Google snippet — no LinkedIn request
        if pol.snippet_first:
            post_data = _snippet_post(result)

        # Tier 2: httpx OG meta — minimal footprint
        if not post_data and direct_fetches < max_direct:
            post_data = await _fetch_og_meta(url)
            if post_data:
                direct_fetches += 1

        # Tier 3: Playwright — only if enabled
        if not post_data and direct_fetches < max_direct:
            post_data = await _scrape_playwright(url)
            if post_data:
                direct_fetches += 1

        # Tier 4: weak snippet fallback
        if not post_data and len(result.get("snippet", "")) > 25:
            post_data = _snippet_post(result) or {
                "text": result["snippet"],
                "author_name": None,
                "author_handle": _handle_from_url(url),
                "posted_at": None,
                "fetch_method": "google_snippet_weak",
            }

        if not post_data:
            continue

        text = post_data.get("text", "")
        if len(text) < 20:
            continue

        tl = text.lower()
        if not any(kw.lower() in tl for kw in keywords + INTENT_KEYWORDS):
            continue

        posts.append({
            "platform": "linkedin",
            "external_id": hashlib.sha256(url.encode()).hexdigest()[:16],
            "url": url,
            "title": None,
            "text": text,
            "author_handle": post_data.get("author_handle", ""),
            "author_display_name": post_data.get("author_name"),
            "author_platform": "linkedin",
            "posted_at": post_data.get("posted_at") or datetime.now(timezone.utc).isoformat(),
            "raw_data": {**post_data, "direct_fetches_used": direct_fetches},
        })

    log.info("linkedin.done", found=len(posts), direct_fetches=direct_fetches)
    return posts

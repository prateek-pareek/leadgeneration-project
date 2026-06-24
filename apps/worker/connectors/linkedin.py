"""
LinkedIn connector — finds public posts via Google Search, then fetches content with Playwright.

Safety measures:
  • Rate limiter: max 4 req/min to google.com, 3 req/min to linkedin.com
  • Playwright stealth: hides webdriver flag, spoofs navigator properties
  • Human-like delays: 4–9s between LinkedIn page loads (randomised)
  • User-Agent rotation: different UA per request
  • robots.txt: checked before every LinkedIn page visit
  • Deduplication: skips already-seen URLs within a scan run
  • Daily cap: 50 LinkedIn touches per 24h, 80 Google searches per 24h
  • Only reads publicly visible posts (no login, no auth)
"""

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from playwright.async_api import async_playwright
import structlog

from utils.scraping import (
    rate_limiter, human_delay, safe_client, stealth_page,
    can_fetch, with_backoff, SeenURLs, random_ua,
)

log = structlog.get_logger()

GOOGLE_URL = "https://www.google.com/search"
INTENT_KEYWORDS = [
    "need help", "looking for", "hire", "find a developer", "build",
    "infrastructure", "cloud", "devops", "struggling with", "can't find",
    "outsource", "managed service", "IT support", "tech team", "CTO",
    "cost too high", "legacy", "migration", "scaling", "security",
]


async def _google_search_linkedin(keywords: list[str], max_results: int) -> list[dict]:
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
            )
            if resp is None or resp.status_code != 200:
                return []

            html = resp.text
            pattern = r'/url\?q=(https://(?:www\.)?linkedin\.com/posts/[^&"\']+)'
            urls = list(dict.fromkeys(re.findall(pattern, html)))
            snippet_pattern = r'<span[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</span>'
            snippets = [re.sub(r'<[^>]+>', '', s) for s in re.findall(snippet_pattern, html, re.DOTALL)]

            for i, url in enumerate(urls[:max_results]):
                results.append({
                    "url": url,
                    "snippet": snippets[i].strip() if i < len(snippets) else "",
                })
        except Exception as e:
            log.warning("linkedin.google_failed", error=str(e))

    await human_delay("google.com")
    return results


async def _scrape_post(url: str) -> dict | None:
    """Scrape one public LinkedIn post with stealth Playwright."""
    ok = await rate_limiter.acquire("linkedin.com")
    if not ok:
        log.warning("linkedin.daily_cap")
        return None

    # Respect robots.txt
    if not await can_fetch(url, ua=random_ua()):
        log.debug("linkedin.robots_blocked", url=url)
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await stealth_page(browser)

            await page.goto(url, wait_until="domcontentloaded", timeout=18000)
            await human_delay("linkedin.com")

            # OG meta tags work even behind login wall
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

            # Try full page content first
            text = ""
            for selector in [
                ".feed-shared-update-v2__description",
                "[data-test-id='main-feed-activity-card__commentary']",
                ".update-components-text",
            ]:
                el = await page.query_selector(selector)
                if el:
                    text = (await el.inner_text()).strip()
                    break

            if not text and og_desc:
                text = og_desc

            if not text or len(text) < 20:
                return None

            return {
                "text": text,
                "author_name": author_name,
                "author_handle": _handle_from_url(url),
                "posted_at": None,
            }
        except Exception as e:
            log.warning("linkedin.scrape_error", url=url, error=str(e))
            return None
        finally:
            await browser.close()


def _handle_from_url(url: str) -> str:
    m = re.search(r'/posts/([^_/?]+)', url)
    return m.group(1) if m else ""


async def fetch(source_config: dict) -> list[dict]:
    keywords = source_config.get("keywords", [])
    max_results = min(source_config.get("max_results", 10), 20)  # conservative cap

    if not keywords:
        return []

    log.info("linkedin.starting", keywords=keywords, max=max_results)
    search_results = await _google_search_linkedin(keywords, max_results)

    seen = SeenURLs()
    posts = []
    sem = asyncio.Semaphore(2)  # max 2 concurrent Playwright (memory)

    async def process(result: dict) -> dict | None:
        async with sem:
            url = result["url"]
            if not seen.check_add(url):
                return None

            post_data = await _scrape_post(url)

            if not post_data:
                # Use Google snippet as fallback
                if len(result.get("snippet", "")) > 40:
                    post_data = {
                        "text": result["snippet"],
                        "author_name": None,
                        "author_handle": _handle_from_url(url),
                        "posted_at": None,
                    }
                else:
                    return None

            text = post_data.get("text", "")
            if not text or len(text) < 20:
                return None

            # Only keep posts with at least one keyword match
            tl = text.lower()
            if not any(kw.lower() in tl for kw in keywords + INTENT_KEYWORDS):
                return None

            return {
                "platform": "linkedin",
                "external_id": hashlib.sha256(url.encode()).hexdigest()[:16],
                "url": url,
                "title": None,
                "text": text,
                "author_handle": post_data.get("author_handle", ""),
                "author_display_name": post_data.get("author_name"),
                "author_platform": "linkedin",
                "posted_at": post_data.get("posted_at") or datetime.now(timezone.utc).isoformat(),
                "raw_data": post_data,
            }

    results = await asyncio.gather(*[process(r) for r in search_results], return_exceptions=True)
    for item in results:
        if isinstance(item, dict):
            posts.append(item)

    log.info("linkedin.done", found=len(posts))
    return posts

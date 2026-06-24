"""
Threads connector — Google Search snippet-first, minimal direct fetches.

Safety: uses Google snippets when possible (zero Threads.net hits),
circuit breaker on blocks, strict rate limits, OG-meta only when needed.
"""

import hashlib
import re
from datetime import datetime, timezone

import structlog

from config import settings
from utils.platform_safety import circuit_breaker, is_blocked, policy_for
from utils.scraping import (
    rate_limiter, human_delay, safe_client, with_backoff, SeenURLs,
)

log = structlog.get_logger()

GOOGLE_URL = "https://www.google.com/search"
SNIPPET_MIN_LEN = 40
INTENT_KEYWORDS = [
    "need help", "looking for", "hire", "find a developer", "build",
    "infrastructure", "cloud", "devops", "struggling with", "outsource",
    "managed service", "IT support", "tech team", "scaling", "migration",
]


async def _google_search_threads(keywords: list[str], max_results: int) -> list[dict]:
    if circuit_breaker.is_open("google.com"):
        return []

    query = f'site:threads.net ({" OR ".join(keywords)})'
    results = []

    ok = await rate_limiter.acquire("google.com")
    if not ok:
        log.warning("threads.google_daily_cap")
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
            if is_blocked(resp.status_code, resp.text):
                return []

            html = resp.text
            pattern = r'/url\?q=(https://(?:www\.)?threads\.net/@[^&"\']+/post/[^&"\']+)'
            urls = list(dict.fromkeys(re.findall(pattern, html)))
            snippet_pattern = r'<span[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</span>'
            snippets = [re.sub(r"<[^>]+>", "", s) for s in re.findall(snippet_pattern, html, re.DOTALL)]

            for i, url in enumerate(urls[:max_results]):
                results.append({
                    "url": url,
                    "snippet": snippets[i].strip() if i < len(snippets) else "",
                })
        except Exception as e:
            log.warning("threads.google_failed", error=str(e))

    await human_delay("google.com")
    return results


def _handle_from_url(url: str) -> str:
    m = re.search(r"/@([^/]+)/post/", url)
    return m.group(1) if m else ""


def _meta_content(html: str, prop: str) -> str | None:
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


async def _fetch_post(url: str) -> dict | None:
    if circuit_breaker.is_open("threads.net"):
        return None

    ok = await rate_limiter.acquire("threads.net")
    if not ok:
        log.warning("threads.daily_cap")
        return None

    async with safe_client() as client:
        try:
            resp = await with_backoff(client.get, url, domain="threads.net", max_attempts=2)
            if resp is None or resp.status_code != 200:
                return None
            if is_blocked(resp.status_code, resp.text):
                return None

            html = resp.text
            og_desc = _meta_content(html, "og:description")
            og_title = _meta_content(html, "og:title")

            author_name = None
            if og_title:
                m = re.match(r"^(.+?) (?:on Threads|•)", og_title)
                if m:
                    author_name = m.group(1).strip()

            text = og_desc or ""
            if not text or len(text) < 15:
                return None

            return {
                "text": text,
                "author_name": author_name,
                "author_handle": _handle_from_url(url),
                "posted_at": None,
                "fetch_method": "og_meta",
            }
        except Exception as e:
            log.warning("threads.fetch_error", url=url, error=str(e))
            return None
        finally:
            await human_delay("threads.net")


async def fetch(source_config: dict) -> list[dict]:
    keywords = source_config.get("keywords", [])
    pol = policy_for("threads.net")
    max_results = min(source_config.get("max_results", 10), 15)
    max_direct = min(settings.scraping_threads_max_direct_per_scan, pol.max_direct_fetches_per_scan)

    if not keywords:
        return []

    log.info("threads.starting", keywords=keywords, max=max_results, snippet_first=pol.snippet_first)
    search_results = await _google_search_threads(keywords, max_results)

    seen = SeenURLs()
    posts = []
    direct_fetches = 0

    for result in search_results:
        url = result["url"]
        if not seen.check_add(url):
            continue

        post_data = None
        snippet = result.get("snippet", "")

        # Tier 1: Google snippet — no Threads request
        if pol.snippet_first and len(snippet) >= SNIPPET_MIN_LEN:
            post_data = {
                "text": snippet,
                "author_name": None,
                "author_handle": _handle_from_url(url),
                "posted_at": None,
                "fetch_method": "google_snippet",
            }

        # Tier 2: direct OG fetch only when needed
        if not post_data and direct_fetches < max_direct:
            post_data = await _fetch_post(url)
            if post_data:
                direct_fetches += 1

        # Tier 3: weak snippet fallback
        if not post_data and len(snippet) > 25:
            post_data = {
                "text": snippet,
                "author_name": None,
                "author_handle": _handle_from_url(url),
                "posted_at": None,
                "fetch_method": "google_snippet_weak",
            }

        if not post_data:
            continue

        text = post_data.get("text", "")
        if len(text) < 15:
            continue

        tl = text.lower()
        if not any(kw.lower() in tl for kw in keywords + INTENT_KEYWORDS):
            continue

        posts.append({
            "platform": "threads",
            "external_id": hashlib.sha256(url.encode()).hexdigest()[:16],
            "url": url,
            "title": None,
            "text": text,
            "author_handle": post_data.get("author_handle", ""),
            "author_display_name": post_data.get("author_name"),
            "author_platform": "threads",
            "posted_at": post_data.get("posted_at") or datetime.now(timezone.utc).isoformat(),
            "raw_data": {**post_data, "direct_fetches_used": direct_fetches},
        })

    log.info("threads.done", found=len(posts), direct_fetches=direct_fetches)
    return posts

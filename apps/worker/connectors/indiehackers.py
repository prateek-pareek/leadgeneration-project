"""
Indie Hackers connector — Google site search for founder posts (snippet-first).

Finds founders discussing hiring, building MVPs, outsourcing, and tech help.
No login required — uses Google snippets to avoid direct scraping.
"""

import hashlib
import re
from datetime import datetime, timezone

import structlog

from utils.platform_safety import circuit_breaker, is_blocked
from utils.scraping import rate_limiter, human_delay, safe_client, with_backoff, SeenURLs

log = structlog.get_logger()

GOOGLE_URL = "https://www.google.com/search"
SNIPPET_MIN_LEN = 35
INTENT_KEYWORDS = [
    "need developer", "looking for", "hire", "outsource", "mvp", "build",
    "technical", "devops", "cloud", "saas", "contractor", "freelancer",
    "tech stack", "agency", "help with",
]


async def _google_search(keywords: list[str], max_results: int) -> list[dict]:
    if circuit_breaker.is_open("google.com"):
        return []

    kw_part = " OR ".join(f'"{k}"' if " " in k else k for k in keywords[:5])
    query = f"site:indiehackers.com ({kw_part})"
    results = []

    ok = await rate_limiter.acquire("google.com")
    if not ok:
        return []

    async with safe_client() as client:
        try:
            resp = await with_backoff(
                client.get,
                GOOGLE_URL,
                params={"q": query, "num": min(max_results, 10), "hl": "en", "tbs": "qdr:m"},
                domain="google.com",
                max_attempts=2,
            )
            if resp is None or resp.status_code != 200 or is_blocked(resp.status_code, resp.text):
                return []

            html = resp.text
            pattern = r'/url\?q=(https://(?:www\.)?indiehackers\.com/[^&"\']+)'
            urls = list(dict.fromkeys(re.findall(pattern, html)))
            snippet_pattern = r'<span[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</span>'
            snippets = [re.sub(r"<[^>]+>", "", s) for s in re.findall(snippet_pattern, html, re.DOTALL)]

            for i, url in enumerate(urls[:max_results]):
                results.append({
                    "url": url,
                    "snippet": snippets[i].strip() if i < len(snippets) else "",
                })
        except Exception as e:
            log.warning("indiehackers.google_failed", error=str(e))

    await human_delay("google.com")
    return results


def _author_from_url(url: str) -> str:
    m = re.search(r"indiehackers\.com/user/([^/?]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"indiehackers\.com/post/([^/?]+)", url)
    return m.group(1)[:40] if m else "indiehackers-member"


async def fetch(source_config: dict) -> list[dict]:
    keywords = source_config.get("keywords", [])
    max_results = min(source_config.get("max_results", 15), 20)

    if not keywords:
        return []

    log.info("indiehackers.starting", keywords=keywords, max=max_results)
    search_hits = await _google_search(keywords, max_results)

    seen = SeenURLs()
    posts: list[dict] = []

    for hit in search_hits:
        url = hit["url"]
        snippet = hit.get("snippet", "")
        if not seen.check_add(url):
            continue
        if len(snippet) < SNIPPET_MIN_LEN:
            continue

        tl = snippet.lower()
        if not any(kw.lower() in tl for kw in keywords + INTENT_KEYWORDS):
            continue

        handle = _author_from_url(url)
        title = snippet.split(".")[0][:120]

        posts.append({
            "platform": "indiehackers",
            "external_id": hashlib.sha256(url.encode()).hexdigest()[:16],
            "url": url,
            "title": title,
            "text": snippet,
            "author_handle": handle,
            "author_display_name": handle.replace("-", " ").title(),
            "author_platform": "indiehackers",
            "author_profile_url": f"https://www.indiehackers.com/user/{handle}" if "/user/" in url else None,
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "engagement": {},
            "language": "en",
            "source_confidence": 0.8,
            "raw_data": {"fetch_method": "google_snippet", "snippet": snippet},
        })

    log.info("indiehackers.done", found=len(posts))
    return posts

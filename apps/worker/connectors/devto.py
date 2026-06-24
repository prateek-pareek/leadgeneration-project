"""
Dev.to connector — searches public articles and discussions.
Uses the free public Dev.to API (no auth required).
"""

from datetime import datetime, timezone
import structlog

from utils.scraping import rate_limiter, human_delay, safe_client, with_backoff

log = structlog.get_logger()

BASE_URL = "https://dev.to/api"
HEADERS = {
    "User-Agent": "ProspectOS/1.0 (contact@acmecorp.com)",
    "Accept": "application/json",
}

# Tags that indicate decision-makers or people with budget/problems
HIGH_VALUE_TAGS = [
    "devops", "cloud", "infrastructure", "kubernetes", "aws", "azure",
    "startup", "entrepreneurship", "productivity", "management",
    "softwareengineering", "discuss",
]


async def fetch(source_config: dict) -> list[dict]:
    """
    source_config: {
        keywords: ["hiring developer", "IT outsourcing"],
        tags: ["devops", "startup"],      # optional tag filter
        max_results: 20,
    }
    """
    keywords = source_config.get("keywords", [])
    tags = source_config.get("tags", HIGH_VALUE_TAGS[:5])
    max_results = min(source_config.get("max_results", 20), 50)

    posts: list[dict] = []
    seen: set[str] = set()

    async with safe_client(ua=HEADERS["User-Agent"]) as client:
        # 1. Search by keyword
        for kw in keywords[:3]:
            if not await rate_limiter.acquire("dev.to"):
                break
            try:
                resp = await with_backoff(
                    client.get,
                    f"{BASE_URL}/articles/search",
                    params={"q": kw, "per_page": 15, "sort": "published_at"},
                    domain="dev.to",
                )
                if resp and resp.status_code == 200:
                    for a in resp.json():
                        _add_article(a, posts, seen, source="search")
                await human_delay("dev.to")
            except Exception as e:
                log.warning("devto.search_failed", keyword=kw, error=str(e))

        # 2. Browse latest articles by tag
        for tag in tags[:4]:
            if len(posts) >= max_results:
                break
            if not await rate_limiter.acquire("dev.to"):
                break
            try:
                resp = await with_backoff(
                    client.get,
                    f"{BASE_URL}/articles",
                    params={"tag": tag, "per_page": 15, "top": 1},
                    domain="dev.to",
                )
                if resp and resp.status_code == 200:
                    for a in resp.json():
                        _add_article(a, posts, seen, source="tag")
                await human_delay("dev.to")
            except Exception as e:
                log.warning("devto.tag_failed", tag=tag, error=str(e))

        # 3. Latest discussions
        if await rate_limiter.acquire("dev.to"):
            try:
                resp = await with_backoff(
                    client.get,
                    f"{BASE_URL}/articles",
                    params={"tag": "discuss", "per_page": 20, "top": 7},
                    domain="dev.to",
                )
                if resp and resp.status_code == 200:
                    for a in resp.json():
                        if any(kw.lower() in (a.get("title", "") + " " + a.get("description", "")).lower() for kw in keywords):
                            _add_article(a, posts, seen, source="discuss")
                await human_delay("dev.to")
            except Exception as e:
                log.warning("devto.discuss_failed", error=str(e))

    log.info("devto.done", found=len(posts))
    return posts[:max_results]


def _add_article(article: dict, posts: list, seen: set, source: str):
    ext_id = f"devto-{article.get('id', '')}"
    if ext_id in seen or not article.get("title"):
        return
    seen.add(ext_id)

    user = article.get("user", {})
    text = f"{article.get('title', '')}\n\n{article.get('description', '')}"

    posts.append({
        "platform": "devto",
        "external_id": ext_id,
        "url": article.get("url", ""),
        "title": article.get("title"),
        "text": text.strip(),
        "author_handle": user.get("username", ""),
        "author_display_name": user.get("name"),
        "author_platform": "devto",
        "posted_at": article.get("published_at") or datetime.now(timezone.utc).isoformat(),
        "raw_data": {
            "tags": article.get("tag_list", []),
            "reactions": article.get("public_reactions_count", 0),
            "comments": article.get("comments_count", 0),
            "reading_time": article.get("reading_time_minutes", 0),
            "source": source,
        },
    })

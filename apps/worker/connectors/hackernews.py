"""
Hacker News connector using the Algolia HN Search API (free, no auth).
Searches for posts matching intent keywords.
"""
import httpx
import structlog
from datetime import datetime, timezone, timedelta

log = structlog.get_logger()

ALGOLIA_HN_URL = "https://hn.algolia.com/api/v1/search"

DEFAULT_KEYWORDS = [
    "need developer",
    "looking for developer",
    "need MVP",
    "building startup",
    "looking for agency",
    "outsource development",
    "need app built",
    "technical cofounder",
    "looking for CTO",
    "need software help",
    "build my app",
    "hire developers",
]


class HackerNewsConnector:
    def __init__(self, keywords: list[str] | None = None):
        self.keywords = keywords or DEFAULT_KEYWORDS

    async def fetch(self, hours_back: int = 48) -> list[dict]:
        cutoff = int((datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp())
        results = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for keyword in self.keywords:
                try:
                    resp = await client.get(ALGOLIA_HN_URL, params={
                        "query": keyword,
                        "tags": "story,ask_hn",
                        "numericFilters": f"created_at_i>{cutoff}",
                        "hitsPerPage": 20,
                    })
                    resp.raise_for_status()
                    data = resp.json()

                    for hit in data.get("hits", []):
                        results.append(self._normalize(hit, keyword))

                except Exception as exc:
                    log.error("hn_fetch_error", keyword=keyword, error=str(exc))

        # Dedupe by objectID
        seen = set()
        deduped = []
        for r in results:
            if r["external_id"] not in seen:
                seen.add(r["external_id"])
                deduped.append(r)

        log.info("hn_fetch_complete", total=len(deduped))
        return deduped

    def _normalize(self, hit: dict, matched_keyword: str) -> dict:
        text = hit.get("story_text") or hit.get("title") or ""
        return {
            "platform": "hackernews",
            "external_id": hit.get("objectID", ""),
            "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            "post_url": f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
            "title": hit.get("title"),
            "text": text,
            "author_handle": hit.get("author", ""),
            "author_name": hit.get("author", ""),
            "author_profile_url": f"https://news.ycombinator.com/user?id={hit.get('author', '')}",
            "posted_at": datetime.fromtimestamp(
                hit.get("created_at_i", 0), tz=timezone.utc
            ).isoformat(),
            "engagement": {
                "points": hit.get("points", 0),
                "comments": hit.get("num_comments", 0),
            },
            "language": "en",
            "source_confidence": 0.9,
            "matched_keyword": matched_keyword,
            "raw_data": hit,
        }


async def fetch(source_config: dict) -> list[dict]:
    keywords = source_config.get("keywords") or None
    max_results = min(source_config.get("max_results", 20), 50)
    connector = HackerNewsConnector(keywords=keywords)
    results = await connector.fetch()
    return results[:max_results]

"""
Reddit connector — public JSON search API.

Safety measures:
  • Reddit requires a descriptive User-Agent (their ToS), included in every request
  • Rate limiting: max 10 req/min (Reddit public limit is 60/min authed, much less unauthed)
  • Human-like delays: 1.5–3.5s between requests (randomised)
  • Exponential backoff on 429/503 responses
  • Daily cap: 300 requests per 24h
  • Deduplication: skips already-seen post IDs within a scan
  • Only reads public subreddits (no login required)
"""

import hashlib
from datetime import datetime, timezone
import structlog

from utils.scraping import (
    rate_limiter, human_delay, safe_client, with_backoff, SeenURLs,
)

log = structlog.get_logger()

# Reddit ToS requires a descriptive UA: "platform:app_name:version (by /u/username)"
REDDIT_UA = "python:ProspectOS:v1.0 (lead discovery tool for IT services; contact: techsupport@ellebeo.com)"

BASE = "https://www.reddit.com"

DEFAULT_SUBREDDITS = [
    "smallbusiness", "Entrepreneur", "startups", "sysadmin",
    "ITCareerQuestions", "msp", "aws", "devops", "cscareerquestions",
    "webdev", "freelance",
]

INTENT_KEYWORDS = [
    "need help", "looking for", "outsource", "vendor", "hire",
    "managed service", "IT support", "devops", "cloud", "infrastructure",
    "developer", "engineering team", "CTO", "technical co-founder",
]


async def _search(client, subreddit: str, query: str, limit: int) -> list[dict]:
    ok = await rate_limiter.acquire("reddit.com")
    if not ok:
        return []

    url = f"{BASE}/r/{subreddit}/search.json"
    try:
        resp = await with_backoff(
            client.get,
            url,
            params={"q": query, "limit": limit, "sort": "new", "restrict_sr": "on", "t": "week"},
            domain="reddit.com",
        )
        if resp is None or resp.status_code != 200:
            return []
    except Exception as e:
        log.warning("reddit.request_failed", subreddit=subreddit, error=str(e))
        return []

    await human_delay("reddit.com")

    try:
        data = resp.json()
        return data.get("data", {}).get("children", [])
    except Exception:
        return []


async def fetch(source_config: dict) -> list[dict]:
    keywords = source_config.get("keywords", [])
    subreddits = [
        s.strip().lstrip("r/")
        for s in source_config.get("subreddit", ",".join(DEFAULT_SUBREDDITS)).split(",")
        if s.strip()
    ]
    max_results = min(source_config.get("max_results", 25), 50)

    if not keywords:
        return []

    query = " OR ".join(keywords[:5])
    seen = SeenURLs()
    posts: list[dict] = []

    async with safe_client(
        ua=REDDIT_UA,
        extra_headers={"Accept": "application/json"},
    ) as client:
        for subreddit in subreddits:
            if len(posts) >= max_results:
                break

            children = await _search(client, subreddit, query, limit=15)

            for child in children:
                post = child.get("data", {})
                if not post:
                    continue

                if post.get("removed_by_category") or post.get("over_18"):
                    continue

                text = (post.get("selftext") or "").strip()
                title = (post.get("title") or "").strip()
                combined = f"{title}\n\n{text}".strip()

                if not combined or len(combined) < 20:
                    continue

                cl = combined.lower()
                if not any(kw.lower() in cl for kw in keywords + INTENT_KEYWORDS):
                    continue

                url = f"https://www.reddit.com{post.get('permalink', '')}"
                ext_id = f"reddit-{post.get('id', hashlib.sha256(url.encode()).hexdigest()[:8])}"

                if not seen.check_add(ext_id):
                    continue

                created_utc = post.get("created_utc", 0)
                posted_at = (
                    datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
                    if created_utc else datetime.now(timezone.utc).isoformat()
                )

                posts.append({
                    "platform": "reddit",
                    "external_id": ext_id,
                    "url": url,
                    "title": title or None,
                    "text": combined,
                    "author_handle": post.get("author", ""),
                    "author_display_name": None,
                    "author_platform": "reddit",
                    "posted_at": posted_at,
                    "raw_data": {
                        "subreddit": subreddit,
                        "score": post.get("score", 0),
                        "num_comments": post.get("num_comments", 0),
                        "upvote_ratio": post.get("upvote_ratio", 0),
                        "flair": post.get("link_flair_text"),
                    },
                })

    log.info("reddit.done", found=len(posts))
    return posts[:max_results]

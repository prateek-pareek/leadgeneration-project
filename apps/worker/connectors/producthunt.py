"""
Product Hunt connector — searches discussions and posts via their public GraphQL API.
No API key required for public data.
"""

import hashlib
from datetime import datetime, timezone
import structlog

from utils.scraping import rate_limiter, human_delay, safe_client, with_backoff

log = structlog.get_logger()

GRAPHQL_URL = "https://www.producthunt.com/frontend/graphql"

HEADERS = {
    "User-Agent": "ProspectOS/1.0 (lead discovery; contact@acmecorp.com)",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Referer": "https://www.producthunt.com",
    "x-requested-with": "XMLHttpRequest",
}

SEARCH_QUERY = """
query SearchPosts($query: String!, $cursor: String) {
  search(query: $query, scope: DISCUSSIONS, first: 20, after: $cursor) {
    edges {
      node {
        ... on Discussion {
          id
          title
          body
          url
          createdAt
          user {
            username
            name
            headline
          }
          commentsCount
          votesCount
        }
      }
    }
    pageInfo { endCursor hasNextPage }
  }
}
"""

POSTS_QUERY = """
query RecentPosts($topic: String!) {
  posts(topic: $topic, order: NEWEST, first: 20) {
    edges {
      node {
        id
        name
        tagline
        description
        url
        createdAt
        user {
          username
          name
        }
        votesCount
        commentsCount
      }
    }
  }
}
"""


async def _graphql(payload: dict) -> dict:
    ok = await rate_limiter.acquire("producthunt.com")
    if not ok:
        return {}
    async with safe_client(extra_headers={k: v for k, v in HEADERS.items() if k != "User-Agent"}) as client:
        resp = await with_backoff(client.post, GRAPHQL_URL, json=payload, domain="producthunt.com")
        if resp is None:
            return {}
        resp.raise_for_status()
        await human_delay("producthunt.com")
        return resp.json()


async def fetch(source_config: dict) -> list[dict]:
    """
    source_config: {
        keywords: ["looking for developer", "need IT help"],
        topics: ["tech", "developer-tools"],   # optional PH topic filters
        max_results: 20,
    }
    """
    keywords = source_config.get("keywords", [])
    topics = source_config.get("topics", ["tech", "developer-tools", "productivity"])
    max_results = min(source_config.get("max_results", 20), 50)

    posts: list[dict] = []
    seen: set[str] = set()

    # 1. Search discussions for keywords
    for kw in keywords[:5]:
        try:
            data = await _graphql({"query": SEARCH_QUERY, "variables": {"query": kw}})
            edges = data.get("data", {}).get("search", {}).get("edges", [])
            for edge in edges:
                node = edge.get("node", {})
                if not node or not node.get("body"):
                    continue
                ext_id = f"ph-disc-{node['id']}"
                if ext_id in seen:
                    continue
                seen.add(ext_id)
                user = node.get("user") or {}
                posts.append({
                    "platform": "producthunt",
                    "external_id": ext_id,
                    "url": f"https://www.producthunt.com{node.get('url','')}",
                    "title": node.get("title"),
                    "text": node.get("body", ""),
                    "author_handle": user.get("username", ""),
                    "author_display_name": user.get("name"),
                    "author_headline": user.get("headline"),
                    "author_platform": "producthunt",
                    "posted_at": node.get("createdAt", datetime.now(timezone.utc).isoformat()),
                    "raw_data": {
                        "votes": node.get("votesCount", 0),
                        "comments": node.get("commentsCount", 0),
                    },
                })
        except Exception as e:
            log.warning("producthunt.search_failed", keyword=kw, error=str(e))

    # 2. Browse recent posts by topic (these people just shipped something = decision makers)
    for topic in topics[:3]:
        if len(posts) >= max_results:
            break
        try:
            data = await _graphql({"query": POSTS_QUERY, "variables": {"topic": topic}})
            edges = data.get("data", {}).get("posts", {}).get("edges", [])
            for edge in edges:
                node = edge.get("node", {})
                if not node:
                    continue
                ext_id = f"ph-post-{node['id']}"
                if ext_id in seen:
                    continue
                seen.add(ext_id)
                user = node.get("user") or {}
                text = f"{node.get('name','')}\n\n{node.get('tagline','')}\n\n{node.get('description','')}"
                posts.append({
                    "platform": "producthunt",
                    "external_id": ext_id,
                    "url": f"https://www.producthunt.com{node.get('url','')}",
                    "title": node.get("name"),
                    "text": text.strip(),
                    "author_handle": user.get("username", ""),
                    "author_display_name": user.get("name"),
                    "author_platform": "producthunt",
                    "posted_at": node.get("createdAt", datetime.now(timezone.utc).isoformat()),
                    "raw_data": {
                        "votes": node.get("votesCount", 0),
                        "comments": node.get("commentsCount", 0),
                        "type": "product_launch",
                    },
                })
        except Exception as e:
            log.warning("producthunt.topic_failed", topic=topic, error=str(e))

    log.info("producthunt.done", found=len(posts))
    return posts[:max_results]

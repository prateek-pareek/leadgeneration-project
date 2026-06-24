"""Dev.to comment publisher — official API."""

import structlog

from config import settings
from utils.scraping import safe_client, with_backoff

log = structlog.get_logger()


async def post_comment(article_url: str, body: str) -> tuple[bool, str | None, str | None]:
    """
    Post a comment on a Dev.to article.
    Returns (success, comment_url, error_message).
    """
    if not settings.devto_api_key:
        return False, None, "DEVTO_API_KEY not configured"

    # Dev.to API accepts article_id or path in commentable
    async with safe_client() as client:
        resp = await with_backoff(
            client.post,
            "https://dev.to/api/comments",
            headers={
                "api-key": settings.devto_api_key,
                "Content-Type": "application/json",
            },
            json={
                "comment": {
                    "body_markdown": body,
                    "commentable_id": article_url,
                    "commentable_type": "Article",
                },
            },
            domain="dev.to",
            max_attempts=2,
        )
        if resp is None:
            return False, None, "request failed"
        if resp.status_code not in (200, 201):
            return False, None, f"HTTP {resp.status_code}: {resp.text[:200]}"

        try:
            data = resp.json()
            url = data.get("url") or data.get("canonical_url")
            return True, url, None
        except Exception as e:
            return True, article_url, str(e)

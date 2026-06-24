"""Reddit comment publisher — OAuth API (optional)."""

import structlog

from config import settings
from utils.scraping import safe_client, with_backoff

log = structlog.get_logger()

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"


async def _get_access_token(client) -> str | None:
    if not settings.reddit_client_id or not settings.reddit_refresh_token:
        return None
    resp = await client.post(
        TOKEN_URL,
        auth=(settings.reddit_client_id, settings.reddit_client_secret or ""),
        data={
            "grant_type": "refresh_token",
            "refresh_token": settings.reddit_refresh_token,
        },
        headers={"User-Agent": settings.reddit_user_agent},
    )
    if resp.status_code != 200:
        log.warning("reddit.token_failed", status=resp.status_code)
        return None
    return resp.json().get("access_token")


def _extract_thing_id(post_url: str) -> str | None:
    # https://www.reddit.com/r/sub/comments/abc123/title/
    parts = post_url.rstrip("/").split("/")
    for i, p in enumerate(parts):
        if p == "comments" and i + 1 < len(parts):
            return f"t3_{parts[i + 1]}"
    return None


async def post_comment(post_url: str, body: str) -> tuple[bool, str | None, str | None]:
    """
    Post a comment on a Reddit thread.
    Returns (success, comment_url, error_message).
    """
    thing_id = _extract_thing_id(post_url)
    if not thing_id:
        return False, None, "could not parse Reddit post URL"

    async with safe_client() as client:
        token = await _get_access_token(client)
        if not token:
            return False, None, "Reddit OAuth not configured"

        resp = await with_backoff(
            client.post,
            f"{API_BASE}/api/comment",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": settings.reddit_user_agent,
            },
            data={"thing_id": thing_id, "text": body},
            domain="reddit.com",
            max_attempts=2,
        )
        if resp is None:
            return False, None, "request failed"
        if resp.status_code != 200:
            return False, None, f"HTTP {resp.status_code}"

        try:
            data = resp.json()
            errors = data.get("json", {}).get("errors") or []
            if errors:
                return False, None, str(errors)
            things = data.get("json", {}).get("data", {}).get("things", [])
            if things:
                permalink = things[0].get("data", {}).get("permalink")
                if permalink:
                    return True, f"https://www.reddit.com{permalink}", None
            return True, post_url, None
        except Exception as e:
            return False, None, str(e)

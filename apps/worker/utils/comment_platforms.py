"""
Platform capabilities for comment posting.

LinkedIn, Threads, and X do not offer safe public comment APIs for third-party tools.
We use human-in-the-loop assist (copy + open post) to avoid account bans.

Reddit and Dev.to support official API posting when credentials are configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config import settings


class PostMode(str, Enum):
    API = "api"           # auto-post via official API
    ASSIST = "assist"     # copy comment + open post URL (human posts)
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CommentPlatform:
    key: str
    post_mode: PostMode
    display_name: str
    assist_note: str


PLATFORMS: dict[str, CommentPlatform] = {
    "reddit": CommentPlatform(
        "reddit", PostMode.API,
        "Reddit",
        "Paste in the comment box on the post.",
    ),
    "devto": CommentPlatform(
        "devto", PostMode.API,
        "Dev.to",
        "Paste as a comment on the article.",
    ),
    "hackernews": CommentPlatform(
        "hackernews", PostMode.ASSIST,
        "Hacker News",
        "Reply on the HN thread — keep it technical and concise.",
    ),
    "hn": CommentPlatform(
        "hn", PostMode.ASSIST,
        "Hacker News",
        "Reply on the HN thread — keep it technical and concise.",
    ),
    "producthunt": CommentPlatform(
        "producthunt", PostMode.ASSIST,
        "Product Hunt",
        "Comment on the launch or discussion thread.",
    ),
    "ph": CommentPlatform(
        "ph", PostMode.ASSIST,
        "Product Hunt",
        "Comment on the launch or discussion thread.",
    ),
    "linkedin": CommentPlatform(
        "linkedin", PostMode.ASSIST,
        "LinkedIn",
        "Open the post, paste your comment, and submit manually. Never use bots — LinkedIn bans automated commenting.",
    ),
    "threads": CommentPlatform(
        "threads", PostMode.ASSIST,
        "Threads",
        "Reply on the thread manually. Automated posting risks account restrictions.",
    ),
    "twitter": CommentPlatform(
        "twitter", PostMode.ASSIST,
        "X / Twitter",
        "Reply to the tweet manually.",
    ),
    "x": CommentPlatform(
        "x", PostMode.ASSIST,
        "X / Twitter",
        "Reply to the tweet manually.",
    ),
    "manual": CommentPlatform(
        "manual", PostMode.ASSIST,
        "Manual",
        "Open the original post and paste your comment.",
    ),
}

COMMENT_PLATFORMS = frozenset(PLATFORMS.keys())


def normalize_platform(platform: str) -> str:
    p = (platform or "").lower().strip()
    if p == "x":
        return "twitter"
    if p == "hn":
        return "hackernews"
    if p == "ph":
        return "producthunt"
    return p


def platform_info(platform: str) -> CommentPlatform:
    key = normalize_platform(platform)
    return PLATFORMS.get(key, CommentPlatform(
        key, PostMode.ASSIST, key.title(), "Open the post and paste your comment.",
    ))


def can_auto_post(platform: str) -> bool:
    info = platform_info(platform)
    if info.post_mode != PostMode.API:
        return False
    key = normalize_platform(platform)
    if key == "reddit":
        return bool(
            settings.comment_auto_post_reddit
            and settings.reddit_client_id
            and settings.reddit_refresh_token
        )
    if key == "devto":
        return bool(settings.comment_auto_post_devto and settings.devto_api_key)
    return False

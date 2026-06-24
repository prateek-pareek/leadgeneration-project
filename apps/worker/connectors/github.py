"""
GitHub connector — finds help-wanted issues and discussions via the public GitHub API.

Discovers founders and teams posting "looking for developer", contractor requests,
and help-wanted issues. No login required (optional GITHUB_TOKEN for higher rate limits).
"""

import hashlib
import re
from datetime import datetime, timezone

import structlog

from config import settings
from utils.scraping import rate_limiter, human_delay, safe_client, with_backoff, SeenURLs

log = structlog.get_logger()

API_BASE = "https://api.github.com"
INTENT_KEYWORDS = [
    "looking for developer", "need developer", "hire developer", "contractor",
    "freelancer", "outsource", "mvp", "build app", "help wanted",
    "technical cofounder", "devops", "web development",
]

ISSUE_NOISE = re.compile(
    r"\b(bump|dependabot|changelog|typo|lint|eslint|prettier|ci fail|unit test)\b",
    re.I,
)


def _headers() -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ProspectOS/1.0 (lead discovery)",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    tl = text.lower()
    checks = [k.lower() for k in keywords if k.strip()]
    checks.extend(INTENT_KEYWORDS)
    return any(k in tl for k in checks)


def _owner_from_issue(item: dict) -> str:
    user = item.get("user") or {}
    return user.get("login") or "unknown"


async def fetch(source_config: dict) -> list[dict]:
    keywords = source_config.get("keywords", [])
    max_results = min(source_config.get("max_results", 20), 30)

    if not keywords:
        keywords = ["looking for developer", "need developer", "hire developer"]

    log.info("github.starting", keywords=keywords, max=max_results)
    seen = SeenURLs()
    posts: list[dict] = []

    async with safe_client() as client:
        for kw in keywords[:4]:
            if len(posts) >= max_results:
                break

            ok = await rate_limiter.acquire("api.github.com")
            if not ok:
                break

            # Search open issues updated recently with intent keywords
            q = f'{kw} in:title,body is:issue is:open comments:>0'
            resp = await with_backoff(
                client.get,
                f"{API_BASE}/search/issues",
                params={"q": q, "sort": "updated", "order": "desc", "per_page": 20},
                headers=_headers(),
                domain="api.github.com",
                max_attempts=2,
            )
            if resp is None or resp.status_code != 200:
                if resp and resp.status_code == 403:
                    log.warning("github.rate_limited", keyword=kw)
                continue

            try:
                items = resp.json().get("items") or []
            except Exception:
                continue

            await human_delay("api.github.com")

            for item in items:
                if len(posts) >= max_results:
                    break

                title = item.get("title") or ""
                body = (item.get("body") or "")[:1500]
                blob = f"{title} {body}"
                if ISSUE_NOISE.search(blob):
                    continue
                if keywords and not _matches_keywords(blob, keywords):
                    continue

                url = item.get("html_url") or ""
                if not url or not seen.check_add(url):
                    continue

                owner = _owner_from_issue(item)
                repo = (item.get("repository_url") or "").split("/repos/")[-1]

                posts.append({
                    "platform": "github",
                    "external_id": f"github:{item.get('id', hashlib.sha256(url.encode()).hexdigest()[:12])}",
                    "url": url,
                    "title": title,
                    "text": f"{title}\n\n{body}".strip(),
                    "author_handle": owner,
                    "author_display_name": owner,
                    "author_platform": "github",
                    "author_profile_url": f"https://github.com/{owner}",
                    "posted_at": item.get("created_at") or datetime.now(timezone.utc).isoformat(),
                    "engagement": {"comments": item.get("comments", 0)},
                    "language": "en",
                    "source_confidence": 0.82,
                    "raw_data": {
                        "repo": repo,
                        "labels": [l.get("name") for l in item.get("labels", [])],
                        "state": item.get("state"),
                        "matched_keyword": kw,
                    },
                })

    log.info("github.done", found=len(posts))
    return posts

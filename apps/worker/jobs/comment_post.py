"""
Comment post job — publishes approved comments or prepares assist workflow.

After human approval:
  • Reddit / Dev.to — auto-post via API when credentials + flag enabled
  • LinkedIn, Threads, X, HN, etc. — assist mode (user copies & posts manually)
"""

import json
import structlog

from publishers import devto as devto_publisher
from publishers import reddit as reddit_publisher
from utils.comment_platforms import can_auto_post, normalize_platform, platform_info

log = structlog.get_logger()


class CommentPostJob:
    def __init__(self, redis_client, db_pool):
        self.redis = redis_client
        self.db = db_pool

    async def run(self, payload: dict) -> None:
        draft_id = payload["draft_id"]
        org_id = payload["org_id"]

        log.info("comment_post_start", draft_id=draft_id)

        async with self.db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    cd.id, cd.lead_id, cd.selected_variant, cd.status,
                    p.url as post_url, p.platform, p.text as post_text
                FROM comment_drafts cd
                LEFT JOIN posts p ON p.id = cd.post_id
                WHERE cd.id = $1 AND cd.org_id = $2
            """, draft_id, org_id)

        if not row:
            log.warning("comment_post_not_found", draft_id=draft_id)
            return
        if row["status"] not in ("approved", "pending_approval"):
            log.info("comment_post_skip_status", draft_id=draft_id, status=row["status"])
            return

        selected = row["selected_variant"]
        if isinstance(selected, str):
            selected = json.loads(selected)
        comment_text = (selected or {}).get("text", "").strip()
        if not comment_text:
            log.warning("comment_post_no_text", draft_id=draft_id)
            return

        platform = normalize_platform(row["platform"] or "manual")
        post_url = row["post_url"] or ""
        info = platform_info(platform)

        posted_url = None
        post_method = "assist"
        error = None

        if can_auto_post(platform):
            success, url, err = await self._api_post(platform, post_url, comment_text)
            if success:
                posted_url = url
                post_method = "api"
            else:
                error = err
                log.warning("comment_post_api_failed", platform=platform, error=err)

        async with self.db.acquire() as conn:
            if posted_url:
                await conn.execute("""
                    UPDATE comment_drafts SET
                        status = 'posted',
                        posted_at = NOW(),
                        posted_url = $1,
                        updated_at = NOW()
                    WHERE id = $2
                """, posted_url, draft_id)
                await conn.execute("""
                    UPDATE leads SET pipeline_stage = 'Comment Posted', updated_at = NOW()
                    WHERE id = $1
                """, row["lead_id"])
                log.info("comment_post_api_success", draft_id=draft_id, platform=platform, url=posted_url)
            else:
                await conn.execute("""
                    UPDATE leads SET pipeline_stage = 'Comment Drafted', updated_at = NOW()
                    WHERE id = $1 AND pipeline_stage IN ('Discovered', 'Qualified', 'Researched')
                """, row["lead_id"])
                log.info(
                    "comment_post_assist_ready",
                    draft_id=draft_id,
                    platform=platform,
                    post_method=post_method,
                    assist_note=info.assist_note,
                    error=error,
                )

    async def _api_post(self, platform: str, post_url: str, text: str):
        if platform == "reddit":
            return await reddit_publisher.post_comment(post_url, text)
        if platform == "devto":
            return await devto_publisher.post_comment(post_url, text)
        return False, None, "unsupported API platform"

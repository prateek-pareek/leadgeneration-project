"""
Normalize job: takes raw posts from a source scan result and upserts
them into the posts + authors tables, then enqueues research per post.
"""
import json
import structlog

log = structlog.get_logger()


class NormalizeJob:
    def __init__(self, redis_client, db_pool):
        self.redis = redis_client
        self.db = db_pool

    async def run(self, payload: dict) -> None:
        posts = payload.get("posts", [])
        org_id = payload["org_id"]
        source_id = payload.get("source_id")

        log.info("normalize_start", count=len(posts), org_id=org_id)

        new_posts = 0
        for post in posts:
            try:
                await self._upsert_post(post, org_id, source_id)
                new_posts += 1
            except Exception as exc:
                log.error("normalize_post_error", url=post.get("url"), error=str(exc))

        log.info("normalize_complete", new_posts=new_posts)

    async def _upsert_post(self, post: dict, org_id: str, source_id: str | None) -> None:
        async with self.db.acquire() as conn:
            # Upsert author
            author_id = None
            if post.get("author_handle"):
                author_id = await conn.fetchval("""
                    INSERT INTO authors (org_id, platform, handle, display_name, profile_url, bio)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (org_id, platform, handle)
                    DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        updated_at = NOW()
                    RETURNING id
                """,
                    org_id,
                    post.get("platform", "unknown"),
                    post["author_handle"],
                    post.get("author_name"),
                    post.get("author_profile_url"),
                    post.get("author_bio"),
                )

            # Upsert post
            external_id = post.get("external_id") or post.get("url", "")[:200]
            platform = post.get("platform", "manual")

            post_id = await conn.fetchval("""
                INSERT INTO posts (
                    org_id, source_id, author_id, external_id, platform,
                    url, text, title, posted_at, engagement,
                    language, source_confidence, raw_data
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                ON CONFLICT (org_id, platform, external_id) DO NOTHING
                RETURNING id
            """,
                org_id, source_id, author_id, external_id, platform,
                post.get("url", ""), post.get("text", ""),
                post.get("title"),
                post.get("posted_at"),
                json.dumps(post.get("engagement", {})),
                post.get("language", "en"),
                post.get("source_confidence"),
                json.dumps(post.get("raw_data", {})),
            )

            if post_id is None:
                return  # already exists

            # Create lead from this post
            lead_id = await conn.fetchval("""
                INSERT INTO leads (org_id, post_id, author_id, source)
                VALUES ($1, $2, $3, $4) RETURNING id
            """, org_id, post_id, author_id, platform)

            # Enqueue research
            await self.redis.lpush("prospectOS:jobs", json.dumps({
                "type": "lead.research",
                "payload": {"lead_id": str(lead_id), "org_id": org_id},
            }))

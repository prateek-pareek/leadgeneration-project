"""
Normalize job: takes raw posts from a source scan result and upserts
them into the posts + authors tables, then enqueues research per post.
"""
import json
import uuid
import structlog
import asyncpg

log = structlog.get_logger()


def _author_display_name(post: dict) -> str | None:
    return post.get("author_display_name") or post.get("author_name")


def _author_profile_url(post: dict) -> str | None:
    if post.get("author_profile_url"):
        return post["author_profile_url"]
    handle = post.get("author_handle")
    platform = post.get("platform", "")
    if not handle:
        return None
    if platform == "threads":
        return f"https://www.threads.net/@{handle}"
    if platform == "linkedin":
        return f"https://www.linkedin.com/in/{handle}"
    if platform == "twitter":
        return f"https://twitter.com/{handle}"
    if platform == "github":
        return f"https://github.com/{handle}"
    if platform == "indiehackers":
        return f"https://www.indiehackers.com/user/{handle}"
    return None


async def process_post(
    db: asyncpg.Connection,
    post_data: dict,
    org_id: str,
    source_id: str | None,
    redis_client=None,
) -> bool:
    """
    Upsert author + post, create lead, enqueue research.
    Returns True when a new post (and lead) was created.
    """
    org_uuid = uuid.UUID(str(org_id))
    source_uuid = uuid.UUID(str(source_id)) if source_id else None

    author_id = None
    handle = post_data.get("author_handle")
    platform = post_data.get("platform", "manual")

    if handle:
        author_id = await db.fetchval(
            """
            INSERT INTO authors (org_id, platform, handle, display_name, profile_url, bio)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (org_id, platform, handle)
            DO UPDATE SET
                display_name = COALESCE(EXCLUDED.display_name, authors.display_name),
                profile_url = COALESCE(EXCLUDED.profile_url, authors.profile_url),
                updated_at = NOW()
            RETURNING id
            """,
            org_uuid,
            platform,
            handle,
            _author_display_name(post_data),
            _author_profile_url(post_data),
            post_data.get("author_bio"),
        )

    external_id = post_data.get("external_id") or (post_data.get("url", "")[:200])
    if not external_id:
        external_id = uuid.uuid4().hex[:16]

    post_id = await db.fetchval(
        """
        INSERT INTO posts (
            org_id, source_id, author_id, external_id, platform,
            url, text, title, posted_at, engagement,
            language, source_confidence, raw_data, is_processed
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,false)
        ON CONFLICT (org_id, platform, external_id) DO NOTHING
        RETURNING id
        """,
        org_uuid,
        source_uuid,
        author_id,
        external_id,
        platform,
        post_data.get("url", ""),
        post_data.get("text", ""),
        post_data.get("title"),
        post_data.get("posted_at"),
        json.dumps(post_data.get("engagement", {})),
        post_data.get("language", "en"),
        post_data.get("source_confidence"),
        json.dumps(post_data.get("raw_data", {})),
    )

    if post_id is None:
        return False

    lead_id = await db.fetchval(
        """
        INSERT INTO leads (org_id, post_id, author_id, source)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        org_uuid,
        post_id,
        author_id,
        platform,
    )

    await db.execute(
        "UPDATE posts SET is_processed = true WHERE id = $1",
        post_id,
    )

    if redis_client is not None:
        await redis_client.lpush(
            "prospectOS:jobs",
            json.dumps({
                "type": "lead.analyze",
                "payload": {"lead_id": str(lead_id), "org_id": str(org_id)},
            }),
        )

    log.info(
        "post_processed",
        post_id=str(post_id),
        lead_id=str(lead_id),
        platform=platform,
        url=post_data.get("url"),
    )
    return True


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
        async with self.db.acquire() as conn:
            for post in posts:
                try:
                    was_new = await process_post(
                        db=conn,
                        post_data=post,
                        org_id=org_id,
                        source_id=source_id,
                        redis_client=self.redis,
                    )
                    if was_new:
                        new_posts += 1
                except Exception as exc:
                    log.error("normalize_post_error", url=post.get("url"), error=str(exc))

        log.info("normalize_complete", new_posts=new_posts)

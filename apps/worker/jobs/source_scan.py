"""
Source scan job — runs when a user triggers a source scan.
Picks the right connector, fetches posts, normalises and upserts them.
"""

import json
import uuid
from datetime import datetime, timezone
import asyncpg
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from connectors import hackernews, reddit, linkedin, twitter, producthunt, devto, google_places
from jobs.normalize import process_post

log = structlog.get_logger()

CONNECTORS = {
    "hackernews": hackernews.fetch,
    "hn": hackernews.fetch,
    "reddit": reddit.fetch,
    "linkedin": linkedin.fetch,
    "twitter": twitter.fetch,
    "x": twitter.fetch,
    "producthunt": producthunt.fetch,
    "ph": producthunt.fetch,
    "devto": devto.fetch,
    "dev.to": devto.fetch,
    "google_places": google_places.fetch,
    "places": google_places.fetch,
}


async def handle(payload: dict, db: asyncpg.Connection) -> None:
    source_id = payload.get("source_id")
    org_id = payload.get("org_id")

    if not source_id or not org_id:
        log.error("source_scan.missing_payload", payload=payload)
        return

    # Load source from DB
    source = await db.fetchrow(
        """
        SELECT id, name, type, config, org_id
        FROM sources
        WHERE id = $1 AND org_id = $2 AND deleted_at IS NULL
        """,
        uuid.UUID(source_id),
        uuid.UUID(org_id),
    )
    if not source:
        log.error("source_scan.source_not_found", source_id=source_id)
        return

    source_type = (source["type"] or "").lower()
    connector_fn = CONNECTORS.get(source_type)
    if not connector_fn:
        log.error("source_scan.unknown_type", type=source_type, source_id=source_id)
        return

    config = source["config"] or {}
    if isinstance(config, str):
        config = json.loads(config)

    log.info(
        "source_scan.starting",
        source_id=source_id,
        type=source_type,
        name=source["name"],
    )

    # Update last_run_at
    await db.execute(
        "UPDATE sources SET last_run_at = $1 WHERE id = $2",
        datetime.now(timezone.utc),
        uuid.UUID(source_id),
    )

    # Run the connector
    try:
        posts = await connector_fn(config)
    except Exception as e:
        log.error("source_scan.connector_error", type=source_type, error=str(e))
        await db.execute(
            "UPDATE sources SET last_error = $1 WHERE id = $2",
            str(e),
            uuid.UUID(source_id),
        )
        return

    log.info("source_scan.fetched", count=len(posts), source=source["name"])

    # Normalize and upsert each post
    new_count = 0
    for post_data in posts:
        try:
            was_new = await process_post(
                db=db,
                post_data=post_data,
                org_id=org_id,
                source_id=source_id,
            )
            if was_new:
                new_count += 1
        except Exception as e:
            log.warning(
                "source_scan.post_error",
                url=post_data.get("url"),
                error=str(e),
            )

    # Update source stats
    await db.execute(
        """
        UPDATE sources
        SET
            last_run_at = $1,
            posts_found = COALESCE(posts_found, 0) + $2,
            last_error = NULL
        WHERE id = $3
        """,
        datetime.now(timezone.utc),
        new_count,
        uuid.UUID(source_id),
    )

    log.info(
        "source_scan.done",
        source=source["name"],
        total=len(posts),
        new=new_count,
    )

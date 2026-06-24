"""
Source scan job — runs when a user triggers a source scan.
Picks the right connector, fetches posts, normalises and upserts them.
"""

import json
import uuid
from datetime import datetime, timezone
import asyncpg
import structlog

from connectors import hackernews, reddit, linkedin, twitter, threads, producthunt, devto, google_places, job_portals, freelance_marketplaces, github, indiehackers
from jobs.normalize import process_post
from utils.scraping import scan_allowed
from utils.platform_safety import circuit_breaker
from utils.scraping_safety import clamp_scan_config, SOURCE_CIRCUIT_DOMAINS, strict_mode

log = structlog.get_logger()

CONNECTORS = {
    "hackernews": hackernews.fetch,
    "hn": hackernews.fetch,
    "reddit": reddit.fetch,
    "linkedin": linkedin.fetch,
    "twitter": twitter.fetch,
    "x": twitter.fetch,
    "threads": threads.fetch,
    "thred": threads.fetch,
    "producthunt": producthunt.fetch,
    "ph": producthunt.fetch,
    "devto": devto.fetch,
    "dev.to": devto.fetch,
    "google_places": google_places.fetch,
    "places": google_places.fetch,
    "job_portals": job_portals.fetch,
    "jobs": job_portals.fetch,
    "job_portal": job_portals.fetch,
    "freelance_marketplaces": freelance_marketplaces.fetch,
    "freelance": freelance_marketplaces.fetch,
    "github": github.fetch,
    "indiehackers": indiehackers.fetch,
    "ih": indiehackers.fetch,
}


async def handle(payload: dict, db: asyncpg.Connection, redis_client=None) -> None:
    source_id = payload.get("source_id")
    org_id = payload.get("org_id")

    if not source_id or not org_id:
        log.error("source_scan.missing_payload", payload=payload)
        return

    source = await db.fetchrow(
        """
        SELECT id, name, type, config, org_id, last_run_at
        FROM sources
        WHERE id = $1 AND org_id = $2
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

    config = clamp_scan_config(source_type, config)

    allowed, cooldown_msg = scan_allowed(source_type, source.get("last_run_at"))
    if not allowed:
        log.warning("source_scan.cooldown", source_id=source_id, type=source_type, msg=cooldown_msg)
        await db.execute(
            "UPDATE sources SET last_error = $1 WHERE id = $2",
            cooldown_msg,
            uuid.UUID(source_id),
        )
        return

    circuit_domains = SOURCE_CIRCUIT_DOMAINS.get(source_type, [])
    blocked, block_msg = circuit_breaker.any_open(circuit_domains)
    if blocked:
        log.warning("source_scan.circuit_open", source_id=source_id, type=source_type, msg=block_msg)
        await db.execute(
            "UPDATE sources SET last_error = $1 WHERE id = $2",
            block_msg,
            uuid.UUID(source_id),
        )
        return

    log.info(
        "source_scan.starting",
        source_id=source_id,
        type=source_type,
        name=source["name"],
        strict_mode=strict_mode(),
        max_results=config.get("max_results"),
    )

    await db.execute(
        "UPDATE sources SET last_run_at = $1 WHERE id = $2",
        datetime.now(timezone.utc),
        uuid.UUID(source_id),
    )

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

    new_count = 0
    for post_data in posts:
        try:
            was_new = await process_post(
                db=db,
                post_data=post_data,
                org_id=org_id,
                source_id=source_id,
                redis_client=redis_client,
            )
            if was_new:
                new_count += 1
        except Exception as e:
            log.warning(
                "source_scan.post_error",
                url=post_data.get("url"),
                error=str(e),
            )

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

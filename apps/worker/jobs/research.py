"""
Research job: given a lead_id, fetch post + author context and run the research pipeline.
Stores result in research_briefs table and enqueues scoring job.
"""
import json
import structlog
from datetime import datetime, timezone

from ai.client import get_client
from ai.prompts.research import RESEARCH_SYSTEM, RESEARCH_USER_TEMPLATE
from models.research import ResearchBrief

log = structlog.get_logger()

MODEL = "smart"


class ResearchJob:
    def __init__(self, redis_client, db_pool):
        self.redis = redis_client
        self.db = db_pool

    async def run(self, payload: dict) -> None:
        lead_id = payload["lead_id"]
        org_id = payload["org_id"]

        log.info("research_start", lead_id=lead_id)

        async with self.db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    l.id as lead_id,
                    l.org_id,
                    p.text as post_text,
                    p.platform,
                    p.posted_at,
                    a.handle as author_handle,
                    a.bio as author_bio
                FROM leads l
                LEFT JOIN posts p ON p.id = l.post_id
                LEFT JOIN authors a ON a.id = l.author_id
                WHERE l.id = $1 AND l.org_id = $2 AND l.deleted_at IS NULL
            """, lead_id, org_id)

        if not row:
            log.warning("research_lead_not_found", lead_id=lead_id)
            return

        client = get_client()
        prompt = RESEARCH_USER_TEMPLATE.format(
            post_text=row["post_text"] or "",
            author_bio=row["author_bio"] or "Not available",
            platform=row["platform"] or "unknown",
            author_handle=row["author_handle"] or "unknown",
            posted_at=str(row["posted_at"]) if row["posted_at"] else "unknown",
        )

        brief = await client.complete_structured(
            model=MODEL,
            messages=[
                {"role": "system", "content": RESEARCH_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            output_model=ResearchBrief,
        )

        async with self.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO research_briefs (
                    lead_id, org_id, company_name, company_description,
                    company_stage, company_size, founder_confidence, is_decision_maker,
                    pain_points, budget_signal, tech_maturity, service_fit,
                    engagement_angle, brief_text, confidence_overall,
                    uncertain_fields, sources_used, model_used, raw_output
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
            """,
                lead_id, org_id,
                brief.company_name, brief.company_description,
                brief.company_stage, brief.company_size,
                brief.founder_confidence, brief.is_decision_maker,
                brief.pain_points, brief.budget_signal,
                brief.tech_maturity, brief.service_fit,
                brief.engagement_angle, brief.brief_text,
                brief.confidence_overall,
                brief.uncertain_fields, brief.sources_used,
                MODEL, brief.model_dump_json(),
            )

        # Enqueue scoring job
        await self.redis.lpush("prospectOS:jobs", json.dumps({
            "type": "lead.score",
            "payload": {"lead_id": lead_id, "org_id": org_id},
        }))

        log.info("research_complete", lead_id=lead_id, confidence=brief.confidence_overall)

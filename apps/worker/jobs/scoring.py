"""
Scoring job: fetch research brief + post context, compute lead score, store result.
If score >= 60 (warm+), enqueue comment draft generation.
"""
import json
import structlog
from datetime import datetime, timezone

from ai.client import get_client
from ai.prompts.scoring import SCORING_SYSTEM, SCORING_USER_TEMPLATE
from models.scoring import LeadScore

log = structlog.get_logger()
MODEL = "smart"
COMMENT_THRESHOLD = 60


class ScoringJob:
    def __init__(self, redis_client, db_pool):
        self.redis = redis_client
        self.db = db_pool

    async def run(self, payload: dict) -> None:
        lead_id = payload["lead_id"]
        org_id = payload["org_id"]

        log.info("scoring_start", lead_id=lead_id)

        async with self.db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    p.text as post_text,
                    p.platform,
                    p.posted_at,
                    a.handle as author_handle,
                    rb.brief_text,
                    rb.pain_points,
                    rb.service_fit,
                    rb.founder_confidence,
                    rb.budget_signal
                FROM leads l
                LEFT JOIN posts p ON p.id = l.post_id
                LEFT JOIN authors a ON a.id = l.author_id
                LEFT JOIN research_briefs rb ON rb.lead_id = l.id
                WHERE l.id = $1 AND l.org_id = $2 AND l.deleted_at IS NULL
                ORDER BY rb.created_at DESC
                LIMIT 1
            """, lead_id, org_id)

        if not row or not row["post_text"]:
            log.warning("scoring_missing_data", lead_id=lead_id)
            return

        research_summary = f"""
Brief: {row['brief_text'] or 'Not available'}
Pain points: {', '.join(row['pain_points'] or [])}
Service fit: {', '.join(row['service_fit'] or [])}
Budget signal: {row['budget_signal'] or 'unknown'}
Founder confidence: {row['founder_confidence'] or 0:.0%}
""".strip()

        prompt = SCORING_USER_TEMPLATE.format(
            post_text=row["post_text"],
            research_brief=research_summary,
            author_handle=row["author_handle"] or "unknown",
            platform=row["platform"] or "unknown",
            posted_at=str(row["posted_at"]) if row["posted_at"] else "unknown",
            today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )

        client = get_client()
        result = await client.complete_structured(
            model=MODEL,
            messages=[
                {"role": "system", "content": SCORING_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            output_model=LeadScore,
        )

        # Determine bucket
        score = result.score
        if score >= 80:
            bucket = "hot"
        elif score >= 60:
            bucket = "warm"
        elif score >= 40:
            bucket = "cold"
        else:
            bucket = "ignore"

        async with self.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO lead_scores (
                    lead_id, org_id, score, bucket, score_version,
                    dimension_scores, top_signals, explanation,
                    recommended_action, model_used
                ) VALUES ($1,$2,$3,$4,'v1',$5,$6,$7,$8,$9)
            """,
                lead_id, org_id, score, bucket,
                json.dumps(result.dimension_scores.model_dump()),
                result.top_signals,
                result.explanation,
                result.recommended_action,
                MODEL,
            )

            # Update lead pipeline stage to Researched if still at Discovered
            await conn.execute("""
                UPDATE leads SET pipeline_stage = 'Researched', updated_at = NOW()
                WHERE id = $1 AND pipeline_stage IN ('Discovered', 'Qualified')
            """, lead_id)

        log.info("scoring_complete", lead_id=lead_id, score=score, bucket=bucket)

        # Auto-enqueue comment drafting for warm+ leads
        if score >= COMMENT_THRESHOLD and result.recommended_action == "draft_comment":
            await self.redis.lpush("prospectOS:jobs", json.dumps({
                "type": "comment.generate",
                "payload": {"lead_id": lead_id, "org_id": org_id},
            }))
            log.info("comment_draft_enqueued", lead_id=lead_id, score=score)

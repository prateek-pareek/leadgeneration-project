"""
Comment draft job: generates 3 comment variants for a lead, runs safety check,
stores in comment_drafts, creates approval record.
"""
import json
import structlog

from ai.client import get_client
from ai.prompts.comment import COMMENT_SYSTEM, COMMENT_USER_TEMPLATE
from ai.prompts.safety import SAFETY_SYSTEM, SAFETY_USER_TEMPLATE
from models.comment import CommentDraftOutput, SafetyResult

log = structlog.get_logger()

MODEL = "smart"


class CommentDraftJob:
    def __init__(self, redis_client, db_pool):
        self.redis = redis_client
        self.db = db_pool

    async def run(self, payload: dict) -> None:
        lead_id = payload["lead_id"]
        org_id = payload["org_id"]

        log.info("comment_draft_start", lead_id=lead_id)

        async with self.db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    p.text as post_text,
                    p.platform,
                    p.id as post_id,
                    rb.brief_text,
                    rb.pain_points,
                    rb.engagement_angle
                FROM leads l
                LEFT JOIN posts p ON p.id = l.post_id
                LEFT JOIN research_briefs rb ON rb.lead_id = l.id
                WHERE l.id = $1 AND l.org_id = $2 AND l.deleted_at IS NULL
                ORDER BY rb.created_at DESC
                LIMIT 1
            """, lead_id, org_id)

        if not row or not row["post_text"]:
            log.warning("comment_draft_missing_data", lead_id=lead_id)
            return

        research_context = f"""
Brief: {row['brief_text'] or 'Not available'}
Pain points: {', '.join(row['pain_points'] or [])}
Suggested angle: {row['engagement_angle'] or 'Not specified'}
""".strip()

        client = get_client()
        prompt = COMMENT_USER_TEMPLATE.format(
            post_text=row["post_text"],
            platform=row["platform"],
            research_brief=research_context,
        )

        output = await client.complete_structured(
            model=MODEL,
            messages=[
                {"role": "system", "content": COMMENT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            output_model=CommentDraftOutput,
        )

        # Safety check on all variants combined
        all_text = " | ".join(v.text for v in output.variants)
        safety_prompt = SAFETY_USER_TEMPLATE.format(
            content_type="public comment",
            content=all_text,
        )
        safety = await client.complete_structured(
            model=MODEL,
            messages=[
                {"role": "system", "content": SAFETY_SYSTEM},
                {"role": "user", "content": safety_prompt},
            ],
            output_model=SafetyResult,
        )

        if not safety.safe and safety.severity == "high":
            log.warning("comment_draft_blocked_safety",
                        lead_id=lead_id,
                        violations=safety.violations)
            return

        variants_json = json.dumps([v.model_dump() for v in output.variants])
        status = "pending_approval" if safety.safe else "pending_review"

        async with self.db.acquire() as conn:
            draft_id = await conn.fetchval("""
                INSERT INTO comment_drafts (
                    lead_id, org_id, post_id, variants,
                    context_used, model_used, status
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                RETURNING id
            """,
                lead_id, org_id,
                row["post_id"],
                variants_json,
                research_context,
                MODEL,
                status,
            )

            if status == "pending_approval":
                await conn.execute("""
                    INSERT INTO approvals (org_id, type, ref_id, lead_id)
                    VALUES ($1, 'comment_draft', $2, $3)
                """, org_id, draft_id, lead_id)

        log.info("comment_draft_complete",
                 lead_id=lead_id,
                 draft_id=draft_id,
                 status=status,
                 safety_ok=safety.safe)

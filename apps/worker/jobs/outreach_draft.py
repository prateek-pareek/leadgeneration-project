"""
Outreach draft job: generates a personalized outreach message for a lead
based on their CRM stage, research brief, and interaction history.
"""
import json
import structlog

from ai.client import get_client
from ai.prompts.outreach import OUTREACH_SYSTEM, OUTREACH_USER_TEMPLATE
from ai.prompts.safety import SAFETY_SYSTEM, SAFETY_USER_TEMPLATE
from models.comment import SafetyResult
from models.outreach import OutreachDraftOutput

log = structlog.get_logger()
MODEL = "smart"


class OutreachDraftJob:
    def __init__(self, redis_client, db_pool):
        self.redis = redis_client
        self.db = db_pool

    async def run(self, payload: dict) -> None:
        lead_id = payload["lead_id"]
        org_id = payload["org_id"]
        message_type = payload.get("message_type", "cold_email")

        log.info("outreach_draft_start", lead_id=lead_id, type=message_type)

        async with self.db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    l.pipeline_stage,
                    l.custom_fields,
                    rb.brief_text,
                    rb.engagement_angle,
                    rb.service_fit,
                    rb.pain_points,
                    a.display_name,
                    a.handle,
                    a.platform
                FROM leads l
                LEFT JOIN LATERAL (
                    SELECT brief_text, engagement_angle, service_fit, pain_points
                    FROM research_briefs WHERE lead_id = l.id
                    ORDER BY created_at DESC LIMIT 1
                ) rb ON true
                LEFT JOIN authors a ON a.id = l.author_id
                WHERE l.id = $1 AND l.org_id = $2 AND l.deleted_at IS NULL
            """, lead_id, org_id)

        if not row or not row["brief_text"]:
            log.warning("outreach_missing_research", lead_id=lead_id)
            return

        research_brief = f"""
Brief: {row['brief_text']}
Pain points: {', '.join(row['pain_points'] or [])}
Service fit: {', '.join(row['service_fit'] or [])}
Engagement angle: {row['engagement_angle'] or 'Not specified'}
Author: {row['display_name'] or row['handle']} on {row['platform']}
""".strip()

        help_seeker_type = "unknown"
        if row["custom_fields"]:
            cf = row["custom_fields"]
            if isinstance(cf, str):
                cf = json.loads(cf)
            help_seeker_type = (cf.get("signal_analysis") or {}).get("help_seeker_type", "unknown")

        prompt = OUTREACH_USER_TEMPLATE.format(
            message_type=message_type,
            research_brief=research_brief,
            pipeline_stage=row["pipeline_stage"],
            interaction_summary="No prior interaction recorded.",
            help_seeker_type=help_seeker_type,
        )

        client = get_client()
        output = await client.complete_structured(
            model=MODEL,
            messages=[
                {"role": "system", "content": OUTREACH_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            output_model=OutreachDraftOutput,
        )

        # Safety check
        safety_prompt = SAFETY_USER_TEMPLATE.format(
            content_type=f"outreach message ({message_type})",
            content=output.body,
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
            log.warning("outreach_blocked_safety", lead_id=lead_id)
            return

        async with self.db.acquire() as conn:
            draft_id = await conn.fetchval("""
                INSERT INTO outreach_drafts (
                    lead_id, org_id, type, subject, body,
                    personalization_notes, model_used, status
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,'pending_approval')
                RETURNING id
            """,
                lead_id, org_id, message_type,
                output.subject, output.body,
                output.personalization_notes, MODEL,
            )

            await conn.execute("""
                INSERT INTO approvals (org_id, type, ref_id, lead_id)
                VALUES ($1, 'outreach_draft', $2, $3)
            """, org_id, draft_id, lead_id)

        log.info("outreach_draft_complete", lead_id=lead_id, draft_id=draft_id, type=message_type)

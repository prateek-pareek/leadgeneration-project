"""
Scoring job: fetch research brief + post context, compute lead score, store result.
Routes to comment, DM, or email outreach based on agency/freelancer signals.
"""
import json
import structlog
from datetime import datetime, timezone

from ai.client import get_client
from ai.prompts.scoring import SCORING_SYSTEM, SCORING_USER_TEMPLATE
from models.scoring import LeadScore

log = structlog.get_logger()
MODEL = "smart"
ENGAGEMENT_THRESHOLD = 60

SOCIAL_PLATFORMS = {
    "reddit", "hackernews", "hn", "devto", "producthunt", "ph", "manual",
    "linkedin", "threads", "twitter", "x", "github", "indiehackers",
}
DM_PLATFORMS = set()


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
                    rb.budget_signal,
                    l.custom_fields
                FROM leads l
                LEFT JOIN posts p ON p.id = l.post_id
                LEFT JOIN authors a ON a.id = l.author_id
                LEFT JOIN LATERAL (
                    SELECT brief_text, pain_points, service_fit, founder_confidence, budget_signal
                    FROM research_briefs WHERE lead_id = l.id
                    ORDER BY created_at DESC LIMIT 1
                ) rb ON true
                WHERE l.id = $1 AND l.org_id = $2 AND l.deleted_at IS NULL
            """, lead_id, org_id)

        if not row or not row["post_text"]:
            log.warning("scoring_missing_data", lead_id=lead_id)
            return

        custom_fields = row["custom_fields"] or {}
        if isinstance(custom_fields, str):
            custom_fields = json.loads(custom_fields)
        signal = custom_fields.get("signal_analysis", {})

        signal_summary = "Not available"
        if signal:
            signal_summary = (
                f"Type: {signal.get('help_seeker_type', 'unknown')}\n"
                f"Intent strength: {signal.get('intent_strength', 0)}\n"
                f"Engagement play: {signal.get('engagement_play', 'skip')}\n"
                f"Signals: {', '.join(signal.get('signals', []))}\n"
                f"Reasoning: {signal.get('reasoning', '')}"
            )

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
            signal_analysis=signal_summary,
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

        score = result.score
        if score >= 80:
            bucket = "hot"
        elif score >= 60:
            bucket = "warm"
        elif score >= 40:
            bucket = "cold"
        else:
            bucket = "ignore"

        # Merge signal routing with AI output
        help_seeker_type = result.help_seeker_type or signal.get("help_seeker_type", "unknown")
        engagement_play = result.engagement_play or signal.get("engagement_play", "skip")
        platform = row["platform"] or ""

        async with self.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO lead_scores (
                    lead_id, org_id, score, bucket, score_version,
                    dimension_scores, top_signals, explanation,
                    recommended_action, model_used
                ) VALUES ($1,$2,$3,$4,'v2',$5,$6,$7,$8,$9)
            """,
                lead_id, org_id, score, bucket,
                json.dumps({
                    **result.dimension_scores.model_dump(),
                    "help_seeker_type": help_seeker_type,
                    "engagement_play": engagement_play,
                }),
                result.top_signals,
                result.explanation,
                result.recommended_action,
                MODEL,
            )

            await conn.execute("""
                UPDATE leads SET pipeline_stage = 'Researched', updated_at = NOW()
                WHERE id = $1 AND pipeline_stage IN ('Discovered', 'Qualified')
            """, lead_id)

        log.info(
            "scoring_complete",
            lead_id=lead_id,
            score=score,
            bucket=bucket,
            help_seeker_type=help_seeker_type,
            engagement_play=engagement_play,
        )

        if score < ENGAGEMENT_THRESHOLD:
            return
        if help_seeker_type == "employee" and engagement_play == "skip":
            return
        if result.recommended_action == "skip":
            return

        await self._enqueue_engagement(
            lead_id=lead_id,
            org_id=org_id,
            score=score,
            platform=platform,
            help_seeker_type=help_seeker_type,
            engagement_play=engagement_play,
            recommended_action=result.recommended_action,
        )

    async def _enqueue_engagement(
        self,
        *,
        lead_id: str,
        org_id: str,
        score: int,
        platform: str,
        help_seeker_type: str,
        engagement_play: str,
        recommended_action: str,
    ) -> None:
        if help_seeker_type not in ("agency", "freelancer", "either", "unknown"):
            return

        # Email / job portal path
        if engagement_play == "cold_email" or platform in ("job_portals", "freelance_marketplaces") or recommended_action == "draft_email":
            await self.redis.lpush("prospectOS:jobs", json.dumps({
                "type": "outreach.generate",
                "payload": {
                    "lead_id": lead_id,
                    "org_id": org_id,
                    "message_type": "cold_email",
                },
            }))
            log.info("outreach_enqueued", lead_id=lead_id, message_type="cold_email")
            return

        # DM path (only when AI explicitly recommends DM, not default for LinkedIn/Threads)
        if recommended_action == "draft_dm":
            msg_type = "linkedin_dm" if platform == "linkedin" else "x_dm"
            await self.redis.lpush("prospectOS:jobs", json.dumps({
                "type": "outreach.generate",
                "payload": {
                    "lead_id": lead_id,
                    "org_id": org_id,
                    "message_type": msg_type,
                },
            }))
            log.info("outreach_enqueued", lead_id=lead_id, message_type=msg_type)
            return

        # Social comment path
        if (
            engagement_play == "social_comment"
            or platform in SOCIAL_PLATFORMS
            or recommended_action == "draft_comment"
        ):
            await self.redis.lpush("prospectOS:jobs", json.dumps({
                "type": "comment.generate",
                "payload": {"lead_id": lead_id, "org_id": org_id},
            }))
            log.info("comment_draft_enqueued", lead_id=lead_id, score=score)
            return

        # Fallback direct outreach
        if recommended_action == "direct_outreach" or engagement_play == "outreach":
            await self.redis.lpush("prospectOS:jobs", json.dumps({
                "type": "outreach.generate",
                "payload": {
                    "lead_id": lead_id,
                    "org_id": org_id,
                    "message_type": "cold_email",
                },
            }))
            log.info("outreach_enqueued", lead_id=lead_id, message_type="cold_email")

"""
Signal analysis job: classifies whether a lead needs an agency, freelancer, or is
hiring an employee. Stores results on the lead and routes the pipeline accordingly.
"""
import json
import structlog

from ai.client import get_client
from ai.prompts.signals import SIGNAL_ANALYSIS_SYSTEM, SIGNAL_ANALYSIS_USER
from models.signals import SignalAnalysis
from utils.signal_analysis import analyze_post_signals

log = structlog.get_logger()

MODEL = "fast"
RESEARCH_THRESHOLD = 0.25  # minimum intent to run full research pipeline


class SignalAnalysisJob:
    def __init__(self, redis_client, db_pool):
        self.redis = redis_client
        self.db = db_pool

    async def run(self, payload: dict) -> None:
        lead_id = payload.get("lead_id")
        org_id = payload.get("org_id")
        post_id = payload.get("post_id")

        if not lead_id and post_id:
            async with self.db.acquire() as conn:
                lead_id = await conn.fetchval(
                    "SELECT id FROM leads WHERE post_id=$1 AND org_id=$2 LIMIT 1",
                    post_id, org_id,
                )

        if not lead_id:
            log.warning("signal_analysis.missing_lead", payload=payload)
            return

        async with self.db.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT l.id, l.tags, l.custom_fields, p.text, p.platform, p.id as post_id
                FROM leads l
                LEFT JOIN posts p ON p.id = l.post_id
                WHERE l.id = $1 AND l.org_id = $2 AND l.deleted_at IS NULL
            """, lead_id, org_id)

        if not row or not row["text"]:
            log.warning("signal_analysis.no_post", lead_id=lead_id)
            return

        post_text = row["text"]
        platform = row["platform"] or "unknown"

        # Fast rule-based pass
        rule_result = analyze_post_signals(post_text, platform)

        # AI refinement when rules are uncertain or text is substantial
        analysis = None
        if rule_result.rule_confidence < 0.7 or rule_result.help_seeker_type in ("unknown", "either"):
            try:
                client = get_client()
                analysis = await client.complete_structured(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": SIGNAL_ANALYSIS_SYSTEM},
                        {"role": "user", "content": SIGNAL_ANALYSIS_USER.format(
                            platform=platform,
                            post_text=post_text[:2000],
                            rule_type=rule_result.help_seeker_type,
                            rule_signals=", ".join(rule_result.signals) or "none",
                        )},
                    ],
                    output_model=SignalAnalysis,
                    temperature=0.1,
                )
            except Exception as exc:
                log.warning("signal_analysis.ai_failed", lead_id=lead_id, error=str(exc))

        if analysis:
            result = {
                "help_seeker_type": analysis.help_seeker_type,
                "intent_strength": analysis.intent_strength,
                "intent_type": analysis.intent_type,
                "signals": analysis.signals,
                "engagement_play": analysis.engagement_play,
                "reasoning": analysis.reasoning,
                "service_categories": analysis.service_categories,
                "source": "ai+rules",
            }
        else:
            result = {
                "help_seeker_type": rule_result.help_seeker_type,
                "intent_strength": rule_result.intent_strength,
                "intent_type": rule_result.intent_type,
                "signals": rule_result.signals,
                "engagement_play": rule_result.engagement_play,
                "reasoning": "Rule-based classification",
                "service_categories": [],
                "source": "rules",
            }

        # Build tags for filtering in UI
        type_tag = f"seeker:{result['help_seeker_type']}"
        play_tag = f"play:{result['engagement_play']}"
        new_tags = [t for t in (row["tags"] or []) if not str(t).startswith(("seeker:", "play:"))]
        new_tags.extend([type_tag, play_tag])

        custom_fields = row["custom_fields"] or {}
        if isinstance(custom_fields, str):
            custom_fields = json.loads(custom_fields)
        custom_fields["signal_analysis"] = result

        async with self.db.acquire() as conn:
            await conn.execute("""
                UPDATE leads SET
                    custom_fields = $1::jsonb,
                    tags = $2,
                    next_action = $3,
                    updated_at = NOW()
                WHERE id = $4 AND org_id = $5
            """,
                json.dumps(custom_fields),
                new_tags,
                _next_action_label(result),
                lead_id,
                org_id,
            )

            await conn.execute("""
                UPDATE posts SET
                    raw_data = COALESCE(raw_data, '{}'::jsonb) || $1::jsonb
                WHERE id = $2
            """, json.dumps({
                "signal_analysis": result,
                "intent_score": result["intent_strength"],
            }), row["post_id"])

        log.info(
            "signal_analysis_complete",
            lead_id=lead_id,
            help_seeker_type=result["help_seeker_type"],
            engagement_play=result["engagement_play"],
            intent=result["intent_strength"],
        )

        # Route pipeline
        should_research = _should_run_research(result)
        if should_research:
            await self.redis.lpush("prospectOS:jobs", json.dumps({
                "type": "lead.research",
                "payload": {"lead_id": str(lead_id), "org_id": str(org_id)},
            }))
        else:
            async with self.db.acquire() as conn:
                await conn.execute("""
                    UPDATE leads SET
                        pipeline_stage = 'Nurture',
                        next_action = 'Low intent — review manually or skip',
                        updated_at = NOW()
                    WHERE id = $1 AND pipeline_stage = 'Discovered'
                """, lead_id)
            log.info("signal_analysis_skipped_research", lead_id=lead_id, reason=result["help_seeker_type"])


def _should_run_research(result: dict) -> bool:
    hst = result.get("help_seeker_type", "none")
    strength = float(result.get("intent_strength", 0))

    if hst == "employee" and strength < 0.55:
        return False
    if hst == "none" and strength < RESEARCH_THRESHOLD:
        return False
    if strength < RESEARCH_THRESHOLD:
        return False
    return hst in ("agency", "freelancer", "either", "unknown", "employee")


def _next_action_label(result: dict) -> str:
    play = result.get("engagement_play", "skip")
    hst = result.get("help_seeker_type", "unknown")
    labels = {
        "social_comment": f"Draft public comment ({hst} seeker)",
        "dm": f"Draft DM outreach ({hst} seeker)",
        "cold_email": f"Draft cold email ({hst} seeker)",
        "outreach": f"Draft direct outreach ({hst} seeker)",
        "skip": "Review — weak or wrong fit",
    }
    return labels.get(play, "Review lead")

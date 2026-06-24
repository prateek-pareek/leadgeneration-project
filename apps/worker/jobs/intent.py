"""
Intent detection job: lightweight classifier to score buying intent
before running the full research pipeline. Uses the fast/local model.
"""
import json
import structlog

from ai.client import get_client

log = structlog.get_logger()

MODEL = "fast"

INTENT_PROMPT = """
Classify the buying intent of this social media post for a software development agency.

Rate from 0.0 to 1.0 how strongly this post signals that the author:
- Needs software/app/website development help
- Is looking to hire developers or an agency
- Is a founder or business owner with a real project

POST:
{post_text}

Return JSON: {{"intent_score": 0.0-1.0, "intent_type": "explicit|implicit|indirect|none", "signals": ["list of specific phrases"]}}
"""


class IntentJob:
    def __init__(self, redis_client, db_pool):
        self.redis = redis_client
        self.db = db_pool

    async def run(self, payload: dict) -> None:
        post_id = payload["post_id"]
        org_id = payload["org_id"]
        post_text = payload.get("text", "")

        if not post_text:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT text FROM posts WHERE id=$1 AND org_id=$2", post_id, org_id
                )
                if row:
                    post_text = row["text"]

        if not post_text:
            return

        client = get_client()
        try:
            raw = await client.complete(
                model=MODEL,
                messages=[{"role": "user", "content": INTENT_PROMPT.format(post_text=post_text[:1000])}],
                temperature=0.1,
                max_tokens=200,
            )
            # Clean JSON from response
            clean = raw.strip().strip("```json").strip("```").strip()
            result = json.loads(clean)
            intent_score = float(result.get("intent_score", 0))
        except Exception as exc:
            log.warning("intent_parse_error", post_id=post_id, error=str(exc))
            intent_score = 0.5  # default to uncertain

        # Store intent score in post metadata
        async with self.db.acquire() as conn:
            await conn.execute("""
                UPDATE posts SET
                    raw_data = raw_data || jsonb_build_object('intent_score', $1::float),
                    updated_at = NOW()
                WHERE id = $2 AND org_id = $3
            """, intent_score, post_id, org_id)

        log.info("intent_complete", post_id=post_id, score=intent_score)

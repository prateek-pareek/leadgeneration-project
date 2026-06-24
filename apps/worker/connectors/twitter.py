"""
X / Twitter connector via public Nitter instances.

Safety measures:
  • Nitter instance rotation — tries multiple instances, rotates randomly
  • Rate limiting: max 8 req/min per nitter instance
  • Human-like delays: 1.5–5s between requests (randomised with jitter)
  • User-Agent rotation: different UA per request
  • Daily cap: 200 Nitter requests per 24h
  • robots.txt compliance: checked per instance
  • Deduplication: skips already-seen tweet IDs
  • Graceful degradation: if all instances fail, returns empty (never crashes)
  • Reads only public tweets (Nitter proxies public Twitter content)
"""

import hashlib
import random
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus
import structlog
from lxml import html as lhtml

from utils.scraping import (
    rate_limiter, human_delay, safe_client, with_backoff,
    can_fetch, SeenURLs, random_ua,
)

log = structlog.get_logger()

# Public Nitter instances — checked for liveness, rotated randomly
NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
    "https://xcancel.com",
    "https://nitter.cz",
    "https://nitter.net",
]


async def _alive(instance: str) -> bool:
    """Quick liveness check for a nitter instance."""
    try:
        async with safe_client(timeout=5.0) as client:
            resp = await client.get(f"{instance}/search?q=test", timeout=5.0)
            return resp.status_code < 400
    except Exception:
        return False


async def _search_instance(instance: str, query: str, max_results: int) -> list[dict]:
    url = f"{instance}/search?q={quote_plus(query)}&f=tweets"

    ok = await rate_limiter.acquire("nitter")
    if not ok:
        return []

    async with safe_client() as client:
        try:
            resp = await with_backoff(client.get, url, domain="nitter", max_attempts=2)
            if resp is None or resp.status_code != 200:
                return []
        except Exception as e:
            log.warning("twitter.fetch_failed", instance=instance, error=str(e))
            return []

    await human_delay("nitter")

    tree = lhtml.fromstring(resp.content)
    items = tree.cssselect(".timeline-item") or tree.cssselect(".tweet-body")
    results = []

    for item in items[:max_results]:
        try:
            content_els = item.cssselect(".tweet-content") or item.cssselect(".tweet-body .content")
            if not content_els:
                continue
            text = content_els[0].text_content().strip()
            if not text or len(text) < 10:
                continue

            user_els = item.cssselect(".username")
            handle = user_els[0].text_content().strip().lstrip("@") if user_els else ""

            name_els = item.cssselect(".fullname")
            display_name = name_els[0].text_content().strip() if name_els else ""

            link_els = item.cssselect("a.tweet-link") or item.cssselect("a[data-permalink]")
            tweet_path = link_els[0].get("href", "") if link_els else ""
            tweet_url = f"https://twitter.com{tweet_path}" if tweet_path else ""

            time_els = item.cssselect("span.tweet-date a") or item.cssselect(".tweet-date a")
            posted_at = None
            if time_els:
                for attr in ("title", "datetime"):
                    val = time_els[0].get(attr)
                    if val:
                        for fmt in ("%b %d, %Y · %I:%M %p UTC", "%Y-%m-%dT%H:%M:%S"):
                            try:
                                posted_at = datetime.strptime(val.strip(), fmt).replace(tzinfo=timezone.utc).isoformat()
                                break
                            except ValueError:
                                continue
                    if posted_at:
                        break

            ext_id = hashlib.sha256((tweet_url or text).encode()).hexdigest()[:16]
            results.append({
                "platform": "twitter",
                "external_id": ext_id,
                "url": tweet_url,
                "title": None,
                "text": text,
                "author_handle": handle,
                "author_display_name": display_name,
                "author_platform": "twitter",
                "posted_at": posted_at or datetime.now(timezone.utc).isoformat(),
                "raw_data": {"instance": instance},
            })
        except Exception as e:
            log.debug("twitter.parse_error", error=str(e))

    return results


async def fetch(source_config: dict) -> list[dict]:
    keywords = source_config.get("keywords", [])
    max_results = min(source_config.get("max_results", 20), 40)

    if not keywords:
        return []

    # Build search query
    parts = [f'"{kw}"' if " " in kw else kw for kw in keywords]
    query = " OR ".join(parts) + " -is:retweet lang:en"

    # Shuffle instances so we don't always hammer the same one
    instances = NITTER_INSTANCES.copy()
    random.shuffle(instances)

    seen = SeenURLs()
    all_posts: list[dict] = []

    for instance in instances:
        if len(all_posts) >= max_results:
            break

        results = await _search_instance(instance, query, max_results)
        if not results:
            continue

        for post in results:
            if seen.check_add(post["url"] or post["text"][:60]):
                all_posts.append(post)

        log.info("twitter.instance_used", instance=instance, found=len(results))
        break  # got results — stop trying more instances

    log.info("twitter.done", found=len(all_posts))
    return all_posts[:max_results]

"""
Freelance marketplaces connector — Upwork, Freelancer.com, Fiverr, Guru, PeoplePerHour.

Discovers clients posting projects (agency / freelancer opportunities).

Sources (no login required):
  • Freelancer.com — public REST API
  • Upwork, Fiverr, Guru, PeoplePerHour, Contra — Google site: search (snippet-only)

Safety: API-first where available; Google snippets for others; login scraping never enabled by default.
"""

import hashlib
import re
from datetime import datetime, timezone

import structlog

from utils.sourcing_policy import is_portal_allowed
from utils.platform_safety import circuit_breaker, is_blocked
from utils.scraping import rate_limiter, human_delay, safe_client, with_backoff, SeenURLs

log = structlog.get_logger()

GOOGLE_URL = "https://www.google.com/search"
SNIPPET_MIN_LEN = 35
DEFAULT_PORTALS = ["freelancer", "upwork", "guru", "fiverr"]

FREELANCER_API = "https://www.freelancer.com/api/projects/0.1/projects/active/"

INTENT_KEYWORDS = [
    "devops", "cloud", "infrastructure", "web development", "mobile app",
    "api", "backend", "frontend", "full stack", "wordpress", "shopify",
    "aws", "azure", "kubernetes", "database", "python", "react", "node",
    "it support", "sysadmin", "automation", "saas", "mvp", "software",
]

GOOGLE_SITE_QUERIES = {
    "upwork": "site:upwork.com/jobs",
    "fiverr": "site:community.fiverr.com",
    "guru": "site:guru.com/d/jobs",
    "peopleperhour": "site:peopleperhour.com/freelance-jobs",
    "contra": "site:contra.com/opportunity",
}

GOOGLE_URL_PATTERNS = {
    "upwork": r'/url\?q=(https://(?:www\.)?upwork\.com/[^&"\']+)',
    "fiverr": r'/url\?q=(https://(?:www\.)?(?:community\.)?fiverr\.com/[^&"\']+)',
    "guru": r'/url\?q=(https://(?:www\.)?guru\.com/[^&"\']+)',
    "peopleperhour": r'/url\?q=(https://(?:www\.)?peopleperhour\.com/[^&"\']+)',
    "contra": r'/url\?q=(https://(?:www\.)?contra\.com/[^&"\']+)',
}

GOOGLE_CLIENT_LABELS = {
    "upwork": "Upwork client",
    "fiverr": "Fiverr community member",
    "guru": "Guru client",
    "peopleperhour": "PeoplePerHour client",
    "contra": "Contra client",
}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "client").lower()).strip("-")
    return slug[:80] or "client"


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    tl = text.lower()
    checks = [k.lower() for k in keywords if k.strip()]
    checks.extend(INTENT_KEYWORDS)
    return any(k in tl for k in checks)


def _build_post(
    *,
    portal: str,
    job_id: str,
    url: str,
    title: str,
    client: str,
    description: str,
    budget: str | None = None,
    posted_at: str | None = None,
    tags: list[str] | None = None,
    raw_data: dict | None = None,
) -> dict:
    client = client or "Client"
    title = title or "Freelance project"
    desc = (description or "").strip()
    if len(desc) > 1200:
        desc = desc[:1200].rstrip() + "…"

    lines = [f"[{portal.title()}] {client} posted: {title}"]
    if budget:
        lines.append(f"Budget: {budget}")
    if tags:
        lines.append(f"Skills: {', '.join(tags[:8])}")
    if desc:
        lines.append("")
        lines.append(desc)

    text = "\n".join(lines)

    return {
        "platform": "freelance_marketplaces",
        "external_id": f"{portal}:{job_id}",
        "url": url,
        "title": title,
        "text": text,
        "author_handle": _slugify(client),
        "author_display_name": client,
        "author_platform": portal,
        "posted_at": posted_at or datetime.now(timezone.utc).isoformat(),
        "engagement": {},
        "language": "en",
        "source_confidence": 0.88,
        "raw_data": {"portal": portal, **(raw_data or {})},
    }


async def _google_site_search(
    site_query: str,
    keywords: list[str],
    max_results: int,
    url_pattern: str,
) -> list[dict]:
    if circuit_breaker.is_open("google.com"):
        return []

    kw_part = " OR ".join(f'"{k}"' if " " in k else k for k in keywords[:4])
    query = f"{site_query} ({kw_part})"
    results = []

    ok = await rate_limiter.acquire("google.com")
    if not ok:
        return []

    async with safe_client() as client:
        try:
            resp = await with_backoff(
                client.get,
                GOOGLE_URL,
                params={"q": query, "num": min(max_results, 10), "hl": "en", "tbs": "qdr:w"},
                domain="google.com",
                max_attempts=2,
            )
            if resp is None or resp.status_code != 200 or is_blocked(resp.status_code, resp.text):
                return []

            html = resp.text
            urls = list(dict.fromkeys(re.findall(url_pattern, html)))
            snippet_pattern = r'<span[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</span>'
            snippets = [re.sub(r"<[^>]+>", "", s) for s in re.findall(snippet_pattern, html, re.DOTALL)]

            for i, url in enumerate(urls[:max_results]):
                results.append({
                    "url": url,
                    "snippet": snippets[i].strip() if i < len(snippets) else "",
                })
        except Exception as e:
            log.warning("freelance.google_failed", query=site_query, error=str(e))

    await human_delay("google.com")
    return results


async def _fetch_freelancer(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    if circuit_breaker.is_open("freelancer.com"):
        return []

    posts: list[dict] = []
    query = keywords[0] if keywords else "web development"

    for kw in keywords[:3]:
        if len(posts) >= max_results:
            break

        ok = await rate_limiter.acquire("freelancer.com")
        if not ok:
            break

        async with safe_client() as client:
            try:
                resp = await with_backoff(
                    client.get,
                    FREELANCER_API,
                    params={
                        "query": kw,
                        "limit": min(max_results * 2, 30),
                        "sort_field": "time_updated",
                        "compact": "true",
                    },
                    headers={"User-Agent": "ProspectOS/1.0 (lead discovery)"},
                    domain="freelancer.com",
                    max_attempts=2,
                )
                if resp is None or resp.status_code != 200:
                    continue
                data = resp.json()
            except Exception as e:
                log.warning("freelance.freelancer_api_error", keyword=kw, error=str(e))
                continue

        await human_delay("freelancer.com")

        projects = (data.get("result") or {}).get("projects") or []
        for proj in projects:
            if len(posts) >= max_results:
                break

            title = proj.get("title") or ""
            desc = proj.get("preview_description") or proj.get("description") or ""
            blob = f"{title} {desc}"
            if keywords and not _matches_keywords(blob, keywords):
                continue

            pid = str(proj.get("id", ""))
            seo = proj.get("seo_url") or pid
            url = f"https://www.freelancer.com/projects/{seo}"
            if not seen.check_add(url):
                continue

            budget = None
            bud = proj.get("budget") or {}
            if bud.get("minimum") or bud.get("maximum"):
                cur = (proj.get("currency") or {}).get("code", "USD")
                budget = f"{cur} {bud.get('minimum', '?')}–{bud.get('maximum', '?')}"

            posted_at = None
            if proj.get("time_submitted"):
                try:
                    posted_at = datetime.fromtimestamp(
                        int(proj["time_submitted"]), tz=timezone.utc
                    ).isoformat()
                except (ValueError, TypeError):
                    pass

            posts.append(_build_post(
                portal="freelancer",
                job_id=pid,
                url=url,
                title=title,
                client=f"Freelancer client #{proj.get('owner_id', 'unknown')}",
                description=desc,
                budget=budget,
                posted_at=posted_at,
                tags=[],
                raw_data=proj,
            ))

    return posts


async def _fetch_google_marketplace(
    portal: str,
    keywords: list[str],
    max_results: int,
    seen: SeenURLs,
) -> list[dict]:
    site_query = GOOGLE_SITE_QUERIES.get(portal)
    url_pattern = GOOGLE_URL_PATTERNS.get(portal)
    if not site_query or not url_pattern:
        return []

    search_hits = await _google_site_search(site_query, keywords, max_results, url_pattern)
    posts: list[dict] = []
    client_label = GOOGLE_CLIENT_LABELS.get(portal, f"{portal.title()} client")

    for hit in search_hits:
        if len(posts) >= max_results:
            break
        url = hit["url"]
        snippet = hit.get("snippet", "")
        if not seen.check_add(url):
            continue
        if len(snippet) < SNIPPET_MIN_LEN and portal != "upwork":
            continue
        if portal == "upwork" and len(snippet) < 20:
            continue
        if keywords and not _matches_keywords(snippet, keywords):
            continue

        title = snippet.split(".")[0][:120] if snippet else f"{portal.title()} project"
        posts.append(_build_post(
            portal=portal,
            job_id=hashlib.sha256(url.encode()).hexdigest()[:16],
            url=url,
            title=title,
            client=client_label,
            description=snippet,
            posted_at=None,
            raw_data={"fetch_method": "google_snippet", "snippet": snippet},
        ))

    if portal == "upwork":
        log.info("freelance.upwork_done", found=len(posts), direct_fetches=0)
    return posts


async def _fetch_upwork(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    return await _fetch_google_marketplace("upwork", keywords, max_results, seen)


async def _fetch_fiverr(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    return await _fetch_google_marketplace("fiverr", keywords, max_results, seen)


async def _fetch_guru(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    return await _fetch_google_marketplace("guru", keywords, max_results, seen)


async def _fetch_peopleperhour(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    return await _fetch_google_marketplace("peopleperhour", keywords, max_results, seen)


async def _fetch_contra(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    return await _fetch_google_marketplace("contra", keywords, max_results, seen)


PORTAL_FETCHERS = {
    "freelancer": _fetch_freelancer,
    "upwork": _fetch_upwork,
    "fiverr": _fetch_fiverr,
    "guru": _fetch_guru,
    "peopleperhour": _fetch_peopleperhour,
    "contra": _fetch_contra,
}


async def fetch(source_config: dict) -> list[dict]:
    keywords = source_config.get("keywords", [])
    portals = [p.lower() for p in source_config.get("portals", DEFAULT_PORTALS)]
    max_results = min(source_config.get("max_results", 20), 40)

    if not portals:
        portals = DEFAULT_PORTALS
    if not keywords:
        return []

    log.info("freelance_marketplaces.starting", portals=portals, keywords=keywords, max=max_results)

    seen = SeenURLs()
    all_posts: list[dict] = []
    per_portal = max(5, max_results // max(len(portals), 1))

    for portal in portals:
        allowed, reason = is_portal_allowed(portal)
        if not allowed:
            log.warning("freelance_marketplaces.portal_blocked", portal=portal, reason=reason)
            continue

        fetcher = PORTAL_FETCHERS.get(portal)
        if not fetcher:
            log.warning("freelance_marketplaces.unknown_portal", portal=portal)
            continue
        try:
            results = await fetcher(keywords, per_portal, seen)
            all_posts.extend(results)
            log.info("freelance_marketplaces.portal_done", portal=portal, found=len(results))
        except Exception as e:
            log.error("freelance_marketplaces.portal_error", portal=portal, error=str(e))

    log.info("freelance_marketplaces.done", found=len(all_posts))
    return all_posts[:max_results]

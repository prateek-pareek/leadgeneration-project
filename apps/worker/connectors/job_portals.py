"""
Job portals connector — discovers hiring companies from public job board APIs.

Supported portals (no auth required):
  • RemoteOK      — https://remoteok.com/api
  • Remotive      — https://remotive.com/api/remote-jobs
  • Arbeitnow     — https://www.arbeitnow.com/api/job-board-api
  • Jobicy        — https://jobicy.com/api/v2/remote-jobs
  • Working Nomads — https://www.workingnomads.com/api/exposed_jobs/
  • Himalayas     — https://himalayas.app/jobs/api
  • We Work Remotely — public RSS category feeds

Job listings are normalised into post-shaped records so they flow through the
same research / scoring pipeline as social posts. The hiring company is treated
as the author — a strong signal for IT services, staff aug, and DevOps leads.
"""

import hashlib
import re
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import structlog

from utils.sourcing_policy import is_portal_allowed
from utils.scraping_safety import inter_portal_delay_sec, strict_mode
from utils.scraping import rate_limiter, human_delay, safe_client, with_backoff, SeenURLs

log = structlog.get_logger()

DEFAULT_PORTALS = ["remoteok", "remotive", "arbeitnow", "jobicy", "workingnomads"]

INTENT_KEYWORDS = [
    "devops", "cloud", "infrastructure", "managed", "outsourc",
    "contract", "consult", "staff aug", "it support", "sysadmin",
    "platform", "sre", "kubernetes", "aws", "azure", "gcp",
]

WWR_FEEDS = {
    "devops": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "programming": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "full_stack": "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "backend": "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "unknown").lower()).strip("-")
    return slug[:80] or "unknown"


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
    company: str,
    description: str,
    location: str | None = None,
    salary: str | None = None,
    posted_at: str | None = None,
    tags: list[str] | None = None,
    raw_data: dict | None = None,
) -> dict:
    company = company or "Unknown Company"
    title = title or "Open role"
    desc = (description or "").strip()
    if len(desc) > 1200:
        desc = desc[:1200].rstrip() + "…"

    lines = [f"{company} is hiring: {title}"]
    if location:
        lines.append(f"Location: {location}")
    if salary:
        lines.append(f"Salary: {salary}")
    if tags:
        lines.append(f"Tags: {', '.join(tags[:8])}")
    if desc:
        lines.append("")
        lines.append(desc)

    text = "\n".join(lines)
    handle = _slugify(company)

    return {
        "platform": "job_portals",
        "external_id": f"{portal}:{job_id}",
        "url": url,
        "title": title,
        "text": text,
        "author_handle": handle,
        "author_display_name": company,
        "author_platform": portal,
        "author_profile_url": None,
        "posted_at": posted_at or datetime.now(timezone.utc).isoformat(),
        "engagement": {},
        "language": "en",
        "source_confidence": 0.85,
        "raw_data": {
            "portal": portal,
            "company": company,
            "title": title,
            "location": location,
            "salary": salary,
            "tags": tags or [],
            **(raw_data or {}),
        },
    }


async def _fetch_remoteok(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    ok = await rate_limiter.acquire("remoteok.com")
    if not ok:
        return []

    posts: list[dict] = []
    async with safe_client() as client:
        resp = await with_backoff(
            client.get,
            "https://remoteok.com/api",
            headers={"User-Agent": "ProspectOS/1.0 (job discovery; contact: techsupport@ellebeo.com)"},
            domain="remoteok.com",
        )
        if resp is None or resp.status_code != 200:
            return []

        try:
            data = resp.json()
        except Exception:
            return []

    await human_delay("remoteok.com")

    for item in data:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        if len(posts) >= max_results:
            break

        title = item.get("position") or item.get("title") or ""
        company = item.get("company") or ""
        description = item.get("description") or ""
        blob = f"{title} {company} {description} {' '.join(item.get('tags') or [])}"
        if keywords and not _matches_keywords(blob, keywords):
            continue

        url = item.get("url") or item.get("apply_url") or f"https://remoteok.com/remote-jobs/{item['id']}"
        if not seen.check_add(url):
            continue

        posted_at = None
        if item.get("date"):
            try:
                posted_at = datetime.fromisoformat(str(item["date"]).replace("Z", "+00:00")).isoformat()
            except ValueError:
                posted_at = None

        posts.append(_build_post(
            portal="remoteok",
            job_id=str(item["id"]),
            url=url,
            title=title,
            company=company,
            description=description,
            location=item.get("location"),
            salary=item.get("salary"),
            posted_at=posted_at,
            tags=item.get("tags") or [],
            raw_data=item,
        ))

    return posts


async def _fetch_remotive(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    ok = await rate_limiter.acquire("remotive.com")
    if not ok:
        return []

    query = keywords[0] if keywords else "devops"
    posts: list[dict] = []
    async with safe_client() as client:
        resp = await with_backoff(
            client.get,
            "https://remotive.com/api/remote-jobs",
            params={"search": query, "limit": min(max_results * 3, 100)},
            domain="remotive.com",
        )
        if resp is None or resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []

    await human_delay("remotive.com")

    for item in data.get("jobs", []):
        if len(posts) >= max_results:
            break

        title = item.get("title") or ""
        company = item.get("company_name") or ""
        description = item.get("description") or ""
        tags = [item.get("job_type", ""), item.get("category", "")]
        blob = f"{title} {company} {description} {' '.join(tags)}"
        if keywords and not _matches_keywords(blob, keywords):
            continue

        url = item.get("url") or ""
        if not url or not seen.check_add(url):
            continue

        posts.append(_build_post(
            portal="remotive",
            job_id=str(item.get("id") or hashlib.sha256(url.encode()).hexdigest()[:12]),
            url=url,
            title=title,
            company=company,
            description=description,
            location=item.get("candidate_required_location"),
            salary=item.get("salary"),
            posted_at=item.get("publication_date"),
            tags=[t for t in tags if t],
            raw_data=item,
        ))

    return posts


async def _fetch_arbeitnow(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    ok = await rate_limiter.acquire("arbeitnow.com")
    if not ok:
        return []

    posts: list[dict] = []
    async with safe_client() as client:
        resp = await with_backoff(
            client.get,
            "https://www.arbeitnow.com/api/job-board-api",
            domain="arbeitnow.com",
        )
        if resp is None or resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []

    await human_delay("arbeitnow.com")

    for item in data.get("data", []):
        if len(posts) >= max_results:
            break

        title = item.get("title") or ""
        company = item.get("company_name") or ""
        description = item.get("description") or ""
        tags = item.get("tags") or []
        blob = f"{title} {company} {description} {' '.join(tags)}"
        if keywords and not _matches_keywords(blob, keywords):
            continue

        slug = item.get("slug") or ""
        url = f"https://www.arbeitnow.com/jobs/{slug}" if slug else ""
        if not url or not seen.check_add(url):
            continue

        posts.append(_build_post(
            portal="arbeitnow",
            job_id=slug or hashlib.sha256(url.encode()).hexdigest()[:12],
            url=url,
            title=title,
            company=company,
            description=description,
            location=item.get("location"),
            salary=None,
            posted_at=item.get("created_at"),
            tags=tags,
            raw_data=item,
        ))

    return posts


def _parse_rss_items(xml_text: str) -> list[dict]:
    root = ElementTree.fromstring(xml_text)
    items = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        items.append({
            "title": title,
            "link": link,
            "description": description,
            "pub_date": pub_date,
        })
    return items


async def _fetch_weworkremotely(
    keywords: list[str],
    max_results: int,
    seen: SeenURLs,
    categories: list[str] | None = None,
) -> list[dict]:
    feeds = categories or list(WWR_FEEDS.keys())
    posts: list[dict] = []

    async with safe_client() as client:
        for category in feeds:
            if len(posts) >= max_results:
                break

            feed_url = WWR_FEEDS.get(category)
            if not feed_url:
                continue

            ok = await rate_limiter.acquire("weworkremotely.com")
            if not ok:
                break

            resp = await with_backoff(client.get, feed_url, domain="weworkremotely.com")
            if resp is None or resp.status_code != 200:
                continue

            await human_delay("weworkremotely.com")

            try:
                items = _parse_rss_items(resp.text)
            except Exception as e:
                log.warning("job_portals.wwr_parse_error", category=category, error=str(e))
                continue

            for item in items:
                if len(posts) >= max_results:
                    break

                title = item["title"]
                # WWR titles are often "Company: Role"
                company, role = title, title
                if ":" in title:
                    company, role = [p.strip() for p in title.split(":", 1)]

                blob = f"{title} {item['description']}"
                if keywords and not _matches_keywords(blob, keywords):
                    continue

                url = item["link"]
                if not url or not seen.check_add(url):
                    continue

                posted_at = None
                if item.get("pub_date"):
                    try:
                        posted_at = parsedate_to_datetime(item["pub_date"]).astimezone(timezone.utc).isoformat()
                    except (ValueError, TypeError):
                        posted_at = None

                posts.append(_build_post(
                    portal="weworkremotely",
                    job_id=hashlib.sha256(url.encode()).hexdigest()[:16],
                    url=url,
                    title=role,
                    company=company,
                    description=item["description"],
                    location="Remote",
                    posted_at=posted_at,
                    tags=[category],
                    raw_data={"category": category, **item},
                ))

    return posts


async def _fetch_jobicy(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    ok = await rate_limiter.acquire("jobicy.com")
    if not ok:
        return []

    tag = keywords[0] if keywords else "developer"
    posts: list[dict] = []
    async with safe_client() as client:
        resp = await with_backoff(
            client.get,
            "https://jobicy.com/api/v2/remote-jobs",
            params={"count": min(max_results * 2, 50), "tag": tag},
            headers={"User-Agent": "ProspectOS/1.0 (job discovery; contact: techsupport@ellebeo.com)"},
            domain="jobicy.com",
        )
        if resp is None or resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []

    await human_delay("jobicy.com")

    for item in data.get("jobs") or []:
        if len(posts) >= max_results:
            break

        title = item.get("jobTitle") or ""
        company = item.get("companyName") or ""
        description = item.get("jobExcerpt") or item.get("jobDescription") or ""
        blob = f"{title} {company} {description}"
        if keywords and not _matches_keywords(blob, keywords):
            continue

        url = item.get("url") or ""
        if not url or not seen.check_add(url):
            continue

        posted_at = item.get("pubDate")
        tags = []
        if item.get("jobIndustry"):
            tags.extend(item["jobIndustry"] if isinstance(item["jobIndustry"], list) else [item["jobIndustry"]])
        if item.get("jobType"):
            tags.append(item["jobType"])

        posts.append(_build_post(
            portal="jobicy",
            job_id=str(item.get("id", hashlib.sha256(url.encode()).hexdigest()[:16])),
            url=url,
            title=title,
            company=company,
            description=description,
            location=item.get("jobGeo"),
            posted_at=posted_at,
            tags=tags,
            raw_data=item,
        ))

    return posts


async def _fetch_workingnomads(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    ok = await rate_limiter.acquire("workingnomads.com")
    if not ok:
        return []

    posts: list[dict] = []
    async with safe_client() as client:
        resp = await with_backoff(
            client.get,
            "https://www.workingnomads.com/api/exposed_jobs/",
            headers={"User-Agent": "ProspectOS/1.0 (job discovery)"},
            domain="workingnomads.com",
            follow_redirects=True,
        )
        if resp is None or resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []

    await human_delay("workingnomads.com")

    if not isinstance(data, list):
        return []

    for item in data:
        if len(posts) >= max_results:
            break
        if not isinstance(item, dict):
            continue

        title = item.get("title") or ""
        description = re.sub(r"<[^>]+>", " ", item.get("description") or "")
        company = item.get("company_name") or item.get("company") or ""
        if not company and ":" in title:
            company, title = [p.strip() for p in title.split(":", 1)]

        blob = f"{title} {company} {description}"
        if keywords and not _matches_keywords(blob, keywords):
            continue

        url = item.get("url") or ""
        if not url or not seen.check_add(url):
            continue

        posts.append(_build_post(
            portal="workingnomads",
            job_id=hashlib.sha256(url.encode()).hexdigest()[:16],
            url=url,
            title=title,
            company=company or "Hiring company",
            description=description.strip(),
            location="Remote",
            posted_at=item.get("pub_date") or item.get("date"),
            tags=[item.get("category")] if item.get("category") else [],
            raw_data=item,
        ))

    return posts


async def _fetch_himalayas(keywords: list[str], max_results: int, seen: SeenURLs) -> list[dict]:
    ok = await rate_limiter.acquire("himalayas.app")
    if not ok:
        return []

    posts: list[dict] = []
    async with safe_client() as client:
        resp = await with_backoff(
            client.get,
            "https://himalayas.app/jobs/api",
            params={"limit": min(max_results * 4, 80), "offset": 0},
            headers={"User-Agent": "ProspectOS/1.0 (job discovery)"},
            domain="himalayas.app",
        )
        if resp is None or resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []

    await human_delay("himalayas.app")

    for item in data.get("jobs") or []:
        if len(posts) >= max_results:
            break

        title = item.get("title") or ""
        company = item.get("companyName") or ""
        description = re.sub(r"<[^>]+>", " ", item.get("excerpt") or item.get("description") or "")
        blob = f"{title} {company} {description} {' '.join(item.get('categories') or [])}"
        if keywords and not _matches_keywords(blob, keywords):
            continue

        url = item.get("applicationLink") or ""
        if not url or not seen.check_add(url):
            continue

        salary = None
        if item.get("minSalary") or item.get("maxSalary"):
            cur = item.get("currency") or "USD"
            salary = f"{cur} {item.get('minSalary', '?')}–{item.get('maxSalary', '?')}"

        posts.append(_build_post(
            portal="himalayas",
            job_id=str(item.get("guid", hashlib.sha256(url.encode()).hexdigest()[:16])),
            url=url,
            title=title,
            company=company,
            description=description.strip(),
            location="Remote",
            salary=salary,
            posted_at=item.get("pubDate"),
            tags=(item.get("categories") or [])[:6],
            raw_data=item,
        ))

    return posts


PORTAL_FETCHERS = {
    "remoteok": _fetch_remoteok,
    "remotive": _fetch_remotive,
    "arbeitnow": _fetch_arbeitnow,
    "jobicy": _fetch_jobicy,
    "workingnomads": _fetch_workingnomads,
    "himalayas": _fetch_himalayas,
    "weworkremotely": _fetch_weworkremotely,
    "wwr": _fetch_weworkremotely,
}


async def fetch(source_config: dict) -> list[dict]:
    keywords = source_config.get("keywords", [])
    portals = [p.lower() for p in source_config.get("portals", DEFAULT_PORTALS)]
    max_results = min(source_config.get("max_results", 20), 50)
    wwr_categories = source_config.get("wwr_categories")

    if not portals:
        portals = DEFAULT_PORTALS

    log.info("job_portals.starting", portals=portals, keywords=keywords, max=max_results, strict=strict_mode())

    seen = SeenURLs()
    all_posts: list[dict] = []
    per_portal = max(3, max_results // max(len(portals), 1))

    for i, portal in enumerate(portals):
        allowed, reason = is_portal_allowed(portal)
        if not allowed:
            log.warning("job_portals.portal_blocked", portal=portal, reason=reason)
            continue

        fetcher = PORTAL_FETCHERS.get(portal)
        if not fetcher:
            log.warning("job_portals.unknown_portal", portal=portal)
            continue

        try:
            if portal in ("weworkremotely", "wwr"):
                results = await fetcher(keywords, per_portal, seen, wwr_categories)
            else:
                results = await fetcher(keywords, per_portal, seen)
            all_posts.extend(results)
            log.info("job_portals.portal_done", portal=portal, found=len(results))
        except Exception as e:
            log.error("job_portals.portal_error", portal=portal, error=str(e))

        if i < len(portals) - 1:
            await asyncio.sleep(inter_portal_delay_sec())

    log.info("job_portals.done", found=len(all_posts))
    return all_posts[:max_results]

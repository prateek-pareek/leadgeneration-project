"""
Sourcing policy — how we fetch lead data without risking account bans.

RULE: Default is NO LOGIN. We only use methods that do not require
user credentials. Authenticated scraping (Upwork login, LinkedIn session, etc.)
is disabled by default because it carries high ban risk.

Auth tiers (safest first):
  PUBLIC_API  — Official or documented public endpoint (Freelancer, RemoteOK, Jobicy)
  RSS         — Public RSS/Atom feeds (We Work Remotely)
  GOOGLE_SNIPPET — Google site: search, snippet only, zero platform hits
  OG_META     — Single public page OG tags via httpx (minimal)
  LOGIN       — BLOCKED unless SCRAPING_ALLOW_AUTHENTICATED_SOURCES=true
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config import settings


class AuthTier(str, Enum):
    PUBLIC_API = "public_api"
    RSS = "rss"
    GOOGLE_SNIPPET = "google_snippet"
    OG_META = "og_meta"
    LOGIN = "login"


@dataclass(frozen=True)
class SourceMethod:
    portal: str
    tier: AuthTier
    requires_login: bool
    ban_risk: str  # low | medium | high
    note: str


# Registry of all supported portals and how we access them
SOURCE_METHODS: dict[str, SourceMethod] = {
    # Job portals — all no-login
    "remoteok": SourceMethod("remoteok", AuthTier.PUBLIC_API, False, "low", "Public JSON API"),
    "remotive": SourceMethod("remotive", AuthTier.PUBLIC_API, False, "low", "Public JSON API"),
    "arbeitnow": SourceMethod("arbeitnow", AuthTier.PUBLIC_API, False, "low", "Public JSON API"),
    "jobicy": SourceMethod("jobicy", AuthTier.PUBLIC_API, False, "low", "Public JSON API"),
    "workingnomads": SourceMethod("workingnomads", AuthTier.PUBLIC_API, False, "low", "Public jobs API"),
    "himalayas": SourceMethod("himalayas", AuthTier.PUBLIC_API, False, "low", "Public jobs API"),
    "weworkremotely": SourceMethod("weworkremotely", AuthTier.RSS, False, "low", "Public RSS feeds"),
    # Freelance — no-login
    "freelancer": SourceMethod("freelancer", AuthTier.PUBLIC_API, False, "low", "Public projects API"),
    "upwork": SourceMethod("upwork", AuthTier.GOOGLE_SNIPPET, False, "low", "Google snippets only — no Upwork login"),
    "fiverr": SourceMethod("fiverr", AuthTier.GOOGLE_SNIPPET, False, "low", "Fiverr community via Google"),
    "guru": SourceMethod("guru", AuthTier.GOOGLE_SNIPPET, False, "low", "Guru projects via Google"),
    "peopleperhour": SourceMethod("peopleperhour", AuthTier.GOOGLE_SNIPPET, False, "low", "PPH projects via Google"),
    "contra": SourceMethod("contra", AuthTier.GOOGLE_SNIPPET, False, "low", "Contra opportunities via Google"),
    # Social — mixed
    "hackernews": SourceMethod("hackernews", AuthTier.PUBLIC_API, False, "low", "Algolia HN API"),
    "reddit": SourceMethod("reddit", AuthTier.PUBLIC_API, False, "low", "Public JSON + descriptive UA"),
    "devto": SourceMethod("devto", AuthTier.PUBLIC_API, False, "low", "Dev.to public API"),
    "github": SourceMethod("github", AuthTier.PUBLIC_API, False, "low", "GitHub issues search API"),
    "indiehackers": SourceMethod("indiehackers", AuthTier.GOOGLE_SNIPPET, False, "low", "Indie Hackers via Google"),
    "producthunt": SourceMethod("producthunt", AuthTier.PUBLIC_API, False, "medium", "Public API"),
    "linkedin": SourceMethod("linkedin", AuthTier.GOOGLE_SNIPPET, False, "medium", "Google snippets; Playwright off by default"),
    "threads": SourceMethod("threads", AuthTier.GOOGLE_SNIPPET, False, "medium", "Google snippets first"),
    "twitter": SourceMethod("twitter", AuthTier.PUBLIC_API, False, "medium", "Nitter public proxy"),
    # Blocked login methods (not implemented)
    "upwork_login": SourceMethod("upwork_login", AuthTier.LOGIN, True, "high", "NOT ENABLED — account ban risk"),
    "linkedin_login": SourceMethod("linkedin_login", AuthTier.LOGIN, True, "high", "NOT ENABLED — account ban risk"),
}


SOFTWARE_DEV_KEYWORDS = [
    "web development", "software development", "full stack", "backend", "frontend",
    "react", "node", "python", "golang", "mobile app", "ios", "android",
    "devops", "cloud", "aws", "azure", "kubernetes", "api development",
    "mvp", "saas", "wordpress", "shopify", "contract developer",
]


def login_sources_allowed() -> bool:
    return settings.scraping_allow_authenticated_sources


def is_portal_allowed(portal: str) -> tuple[bool, str]:
    """Returns (allowed, reason). Blocks login-tier unless explicitly enabled."""
    method = SOURCE_METHODS.get(portal)
    if not method:
        return True, ""
    if method.requires_login and not login_sources_allowed():
        return False, f"{portal} requires login — disabled to protect your account (set SCRAPING_ALLOW_AUTHENTICATED_SOURCES=true to override)"
    return True, ""


def no_login_portals(category: str) -> list[str]:
    """Return portal keys for a category that don't need login."""
    if category == "job_portals":
        keys = ["remoteok", "remotive", "arbeitnow", "jobicy", "workingnomads", "himalayas", "weworkremotely", "wwr"]
    elif category == "freelance_marketplaces":
        keys = ["freelancer", "upwork", "fiverr", "guru", "peopleperhour", "contra"]
    else:
        return []
    return [k for k in keys if not SOURCE_METHODS.get(k, SourceMethod(k, AuthTier.PUBLIC_API, False, "low", "")).requires_login]

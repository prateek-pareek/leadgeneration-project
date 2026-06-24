"""
Rule-based signal detection for hiring / help-seeking posts.

Classifies whether the author likely needs an agency, freelancer, or is hiring
a full-time employee (not our fit). Used before AI analysis for fast filtering.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SignalResult:
    help_seeker_type: str  # agency | freelancer | either | employee | unknown | none
    intent_strength: float  # 0.0 - 1.0
    intent_type: str  # explicit | implicit | indirect | none
    signals: list[str] = field(default_factory=list)
    engagement_play: str = "skip"  # social_comment | dm | cold_email | outreach | skip
    rule_confidence: float = 0.0


AGENCY_PATTERNS = [
    r"\bagency\b", r"\bagencies\b", r"\boutsource\b", r"\boutsourcing\b",
    r"\bmanaged service", r"\bmsp\b", r"\bconsulting firm\b", r"\bconsultancy\b",
    r"\bstaff aug", r"\bstaff augmentation\b", r"\bdedicated team\b",
    r"\bdevelopment partner\b", r"\bvendor\b", r"\bservice provider\b",
    r"\bneed a team\b", r"\bhire (?:a |an )?(?:dev|development) (?:shop|agency)\b",
]

FREELANCER_PATTERNS = [
    r"\bfreelanc", r"\bcontractor\b", r"\bcontract role\b", r"\bcontract position\b",
    r"\bconsultant\b", r"\bpart[- ]time\b", r"\bhourly\b", r"\bgig\b",
    r"\bindependent\b", r"\b1099\b", r"\bproject[- ]based\b",
    r"\bneed (?:a |an )?(?:dev|developer|engineer) for\b",
    r"\blooking for (?:a |an )?(?:dev|developer|freelancer)\b",
]

EMPLOYEE_PATTERNS = [
    r"\bfull[- ]time\b", r"\bfte\b", r"\bpermanent (?:role|position)\b",
    r"\bjoin our team\b", r"\bwe(?:'re| are) hiring\b", r"\bopen position\b",
    r"\bjob opening\b", r"\bsalary range\b", r"\bbenefits package\b",
    r"\bequity and benefits\b", r"\bon[- ]site\b", r"\bw-2\b",
]

HELP_PATTERNS = [
    r"\bneed help\b", r"\blooking for\b", r"\bhire\b", r"\bhiring\b",
    r"\bbuild (?:my|our|a)\b", r"\bcan(?:'t| not) find\b", r"\bstruggling with\b",
    r"\brecommend\b", r"\bsuggestions?\b", r"\bwho (?:can|should)\b",
    r"\banyone know\b", r"\bhelp (?:me|us)\b", r"\bneed (?:a |an )?(?:dev|developer|team)\b",
]

SOCIAL_PLATFORMS = {
    "reddit", "hackernews", "hn", "devto", "producthunt", "ph", "manual",
    "linkedin", "threads", "twitter", "x", "github", "indiehackers",
}
DM_PLATFORMS = set()  # DM outreach is AI-scored separately, not default for public posts
EMAIL_PLATFORMS = {"job_portals", "freelance_marketplaces"}


def _find_matches(text: str, patterns: list[str]) -> list[str]:
    tl = text.lower()
    hits = []
    for pat in patterns:
        m = re.search(pat, tl, re.IGNORECASE)
        if m:
            hits.append(m.group(0))
    return hits


def _engagement_play(help_seeker_type: str, platform: str) -> str:
    if help_seeker_type in ("none", "employee", "unknown"):
        return "skip"
    if platform in EMAIL_PLATFORMS:
        return "cold_email"
    if platform in DM_PLATFORMS:
        return "dm"
    if platform in SOCIAL_PLATFORMS:
        return "social_comment"
    return "outreach"


def analyze_post_signals(text: str, platform: str = "unknown") -> SignalResult:
    if not text or len(text.strip()) < 15:
        return SignalResult(
            help_seeker_type="none",
            intent_strength=0.0,
            intent_type="none",
            engagement_play="skip",
        )

    agency_hits = _find_matches(text, AGENCY_PATTERNS)
    freelancer_hits = _find_matches(text, FREELANCER_PATTERNS)
    employee_hits = _find_matches(text, EMPLOYEE_PATTERNS)
    help_hits = _find_matches(text, HELP_PATTERNS)

    signals = []
    if agency_hits:
        signals.append(f"agency: {agency_hits[0]}")
    if freelancer_hits:
        signals.append(f"freelancer: {freelancer_hits[0]}")
    if employee_hits:
        signals.append(f"employee: {employee_hits[0]}")
    for h in help_hits[:3]:
        signals.append(f"help: {h}")

    # Classify primary type
    agency_score = len(agency_hits) * 2 + (1 if "outsource" in text.lower() else 0)
    freelancer_score = len(freelancer_hits) * 2
    employee_score = len(employee_hits) * 2

    if agency_score > 0 and freelancer_score > 0:
        help_seeker_type = "either"
    elif agency_score > freelancer_score and agency_score > 0:
        help_seeker_type = "agency"
    elif freelancer_score > agency_score and freelancer_score > 0:
        help_seeker_type = "freelancer"
    elif employee_score > 0 and agency_score == 0 and freelancer_score == 0:
        help_seeker_type = "employee"
    elif help_hits and platform in ("job_portals", "freelance_marketplaces"):
        # Job listings without contractor signals → likely employee hire
        help_seeker_type = "employee"
    elif help_hits:
        help_seeker_type = "unknown"
    else:
        help_seeker_type = "none"

    # Intent strength
    hit_count = len(agency_hits) + len(freelancer_hits) + len(help_hits)
    if help_seeker_type == "none":
        intent_strength = 0.0
        intent_type = "none"
    elif help_seeker_type == "employee":
        intent_strength = min(0.4 + employee_score * 0.1, 0.7)
        intent_type = "indirect"
    elif agency_hits or freelancer_hits:
        intent_strength = min(0.55 + hit_count * 0.12, 1.0)
        intent_type = "explicit"
    elif help_hits:
        intent_strength = min(0.35 + hit_count * 0.1, 0.75)
        intent_type = "implicit"
    else:
        intent_strength = 0.2
        intent_type = "indirect"

    # Job portal listings are companies hiring — treat as agency/freelancer opportunity
    if platform in ("job_portals", "freelance_marketplaces") and help_seeker_type == "employee":
        if any(k in text.lower() for k in ("contract", "freelance", "consult", "agency", "outsource")):
            help_seeker_type = "either"
            intent_strength = max(intent_strength, 0.6)
        else:
            # Company hiring tech role = potential staff aug / agency lead
            help_seeker_type = "agency"
            intent_strength = max(intent_strength, 0.5)
            signals.append("job_listing: company actively hiring tech")

    rule_confidence = min(0.4 + hit_count * 0.15, 0.95) if signals else 0.2
    engagement_play = _engagement_play(help_seeker_type, platform)

    return SignalResult(
        help_seeker_type=help_seeker_type,
        intent_strength=round(intent_strength, 3),
        intent_type=intent_type,
        signals=signals[:8],
        engagement_play=engagement_play,
        rule_confidence=round(rule_confidence, 3),
    )

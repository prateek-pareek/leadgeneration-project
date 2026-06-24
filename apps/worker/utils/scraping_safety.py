"""
Scraping safety — effective limits, scan cooldowns, and strict-mode enforcement.

When SCRAPING_STRICT_MODE=true (default), all rate limits and delays are tightened
automatically so portals stay usable long-term without account blocks.
"""

from __future__ import annotations

from config import settings

# Minimum seconds between full source scans (by source type)
SOURCE_SCAN_INTERVAL_SEC: dict[str, int] = {
    "linkedin": 7200,              # 2 hours
    "threads": 3600,               # 1 hour
    "twitter": 1800,
    "x": 1800,
    "indiehackers": 3600,          # uses Google
    "freelance_marketplaces": 3600,  # mix of API + Google
    "reddit": 1200,                # 20 min
    "github": 900,
    "job_portals": 900,            # 15 min — multiple API calls per scan
    "hackernews": 600,
    "devto": 600,
    "producthunt": 900,
    "google_places": 3600,
}

# Domains to check circuit breaker before starting a scan
SOURCE_CIRCUIT_DOMAINS: dict[str, list[str]] = {
    "linkedin": ["linkedin.com", "google.com"],
    "threads": ["threads.net", "google.com"],
    "twitter": ["nitter"],
    "x": ["nitter"],
    "indiehackers": ["google.com"],
    "freelance_marketplaces": ["google.com", "freelancer.com"],
    "reddit": ["reddit.com"],
    "github": ["api.github.com"],
}


def strict_mode() -> bool:
    return settings.scraping_strict_mode


def strict_multiplier() -> float:
    return 0.5 if strict_mode() else 1.0


def effective_rpm(base_rpm: int) -> int:
    """Lower requests/min in strict mode."""
    if strict_mode():
        return max(1, int(base_rpm * 0.45))
    return base_rpm


def effective_daily_cap(base_cap: int) -> int:
    if strict_mode():
        return max(10, int(base_cap * 0.4))
    return base_cap


def max_results_for_scan(source_type: str, requested: int) -> int:
    cap = settings.scraping_max_results_per_scan_strict if strict_mode() else settings.scraping_max_results_per_scan
    return min(requested, cap)


def max_portals_per_scan(source_type: str, requested: int) -> int:
    if source_type not in ("job_portals", "freelance_marketplaces"):
        return requested
    cap = settings.scraping_max_portals_per_scan_strict if strict_mode() else settings.scraping_max_portals_per_scan
    return min(requested, cap)


def inter_portal_delay_sec() -> float:
    """Pause between job/freelance portal fetches."""
    import random
    if strict_mode():
        return random.uniform(4.0, 10.0)
    return random.uniform(1.5, 4.0)


def scan_interval_sec(source_type: str) -> int:
    base = SOURCE_SCAN_INTERVAL_SEC.get(source_type, 600)
    if strict_mode():
        return int(base * 1.5)
    return base


def linkedin_max_direct() -> int:
    if strict_mode():
        return min(settings.scraping_linkedin_max_direct_per_scan, 0)
    return settings.scraping_linkedin_max_direct_per_scan


def threads_max_direct() -> int:
    if strict_mode():
        return min(settings.scraping_threads_max_direct_per_scan, 2)
    return settings.scraping_threads_max_direct_per_scan


def clamp_scan_config(source_type: str, config: dict) -> dict:
    """Apply safety caps to source config before connector runs."""
    cfg = dict(config or {})
    max_r = cfg.get("max_results", 20)
    cfg["max_results"] = max_results_for_scan(source_type, int(max_r))
    if "portals" in cfg and isinstance(cfg["portals"], list):
        cfg["portals"] = cfg["portals"][: max_portals_per_scan(source_type, len(cfg["portals"]))]
    return cfg

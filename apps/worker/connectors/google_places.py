"""
Google Places connector — finds local businesses WITHOUT websites.

Why this matters for IT services:
  A business with no website is actively underserved in digital infrastructure.
  They're prime candidates for: web development, cloud setup, IT support,
  managed services, and digital transformation.

Legal / ToS compliance:
  ✅ Uses the official Google Places API (Maps Platform)
  ✅ Data is explicitly licensed for commercial use under Google Maps Platform ToS
  ✅ Only accesses publicly available business information
  ✅ No personal data collected (business records only)
  ✅ Respects Google's QPS and billing limits
  ✅ Attribution stored in raw_data as required
  ✅ API key read from env — never hardcoded

Rate limits (free tier = $200/month credit):
  • Text Search:    $17 / 1000 requests  (~11,700 free/month)
  • Place Details:  $17 / 1000 requests  (~11,700 free/month)
  • We cap at 50 results per scan = ~100 API calls max per run

Required env: GOOGLE_API_KEY
"""

import hashlib
import os
from datetime import datetime, timezone
import structlog

from utils.scraping import rate_limiter, human_delay, safe_client, with_backoff

log = structlog.get_logger()

PLACES_TEXT_SEARCH = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS = "https://maps.googleapis.com/maps/api/place/details/json"
PLACES_NEARBY = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

# Business types that commonly lack websites and need IT services
DEFAULT_BUSINESS_TYPES = [
    "restaurant",
    "beauty_salon",
    "hair_care",
    "gym",
    "lawyer",
    "accountant",
    "dentist",
    "doctor",
    "veterinary_care",
    "real_estate_agency",
    "car_repair",
    "plumber",
    "electrician",
    "contractor",
    "dry_cleaning",
    "pharmacy",
    "insurance_agency",
    "travel_agency",
    "clothing_store",
    "furniture_store",
]

# Fields to request from Place Details (minimise billing by requesting only what we need)
DETAIL_FIELDS = ",".join([
    "name",
    "website",
    "formatted_phone_number",
    "international_phone_number",
    "formatted_address",
    "types",
    "rating",
    "user_ratings_total",
    "url",
    "business_status",
])

IT_SERVICE_FIT_MAP = {
    "restaurant": "needs website, online ordering, POS system, social media",
    "beauty_salon": "needs booking system, website, online presence",
    "hair_care": "needs booking system, website, online presence",
    "gym": "needs website, membership management, booking system",
    "lawyer": "needs professional website, client portal, document management",
    "accountant": "needs secure client portal, cloud accounting, website",
    "dentist": "needs appointment booking, patient portal, HIPAA compliance",
    "doctor": "needs EHR integration, patient portal, HIPAA compliance",
    "veterinary_care": "needs appointment system, website, pet management",
    "real_estate_agency": "needs CRM, property listings website, digital marketing",
    "car_repair": "needs appointment booking, invoicing software, website",
    "plumber": "needs job scheduling app, website, mobile access",
    "electrician": "needs job scheduling app, website, estimates software",
    "contractor": "needs project management tools, website, digital estimates",
    "dry_cleaning": "needs POS system, pickup/delivery app, website",
    "pharmacy": "needs inventory management, HIPAA compliance, website",
    "insurance_agency": "needs CRM, document management, secure portal",
    "travel_agency": "needs booking platform, website, CRM",
    "clothing_store": "needs e-commerce website, inventory management, POS",
    "furniture_store": "needs e-commerce website, inventory, CRM",
}


def _api_key() -> str | None:
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")


async def _text_search(client, query: str, location: str, next_page_token: str | None = None) -> dict:
    """Execute one Google Places Text Search request."""
    ok = await rate_limiter.acquire("google.com")
    if not ok:
        return {}

    params: dict = {"key": _api_key(), "language": "en"}

    if next_page_token:
        params["pagetoken"] = next_page_token
    else:
        params["query"] = f"{query} in {location}"

    resp = await with_backoff(
        client.get,
        PLACES_TEXT_SEARCH,
        params=params,
        domain="google.com",
    )
    if resp is None or resp.status_code != 200:
        return {}
    await human_delay("google.com")
    return resp.json()


async def _get_details(client, place_id: str) -> dict:
    """Fetch Place Details for one business."""
    ok = await rate_limiter.acquire("google.com")
    if not ok:
        return {}

    resp = await with_backoff(
        client.get,
        PLACES_DETAILS,
        params={
            "place_id": place_id,
            "fields": DETAIL_FIELDS,
            "key": _api_key(),
            "language": "en",
        },
        domain="google.com",
    )
    if resp is None or resp.status_code != 200:
        return {}
    await human_delay("google.com")
    data = resp.json()
    return data.get("result", {})


def _build_profile_text(detail: dict, it_fit: str) -> str:
    """Synthesise a readable business profile that the AI pipeline can analyse."""
    name = detail.get("name", "Unknown Business")
    address = detail.get("formatted_address", "")
    phone = detail.get("formatted_phone_number") or detail.get("international_phone_number", "")
    rating = detail.get("rating", 0)
    review_count = detail.get("user_ratings_total", 0)
    types = [t.replace("_", " ").title() for t in detail.get("types", []) if t not in ("establishment", "point_of_interest")]
    category = ", ".join(types[:3]) if types else "Local Business"

    lines = [
        f"BUSINESS: {name}",
        f"Category: {category}",
        f"Location: {address}",
    ]
    if phone:
        lines.append(f"Phone: {phone}")
    if rating:
        lines.append(f"Rating: {rating}/5 ({review_count} reviews)")
    lines += [
        "",
        "⚠ No website found — this business has no online presence.",
        f"IT services opportunity: {it_fit}",
        "",
        "LEAD CONTEXT: This is a local business without a website. "
        "They likely handle everything via phone/walk-in. "
        "A discovery call focused on their biggest operational pain point "
        "(booking, payments, customer management, online visibility) "
        "would open the door to managed IT or digital services.",
    ]
    return "\n".join(lines)


async def fetch(source_config: dict) -> list[dict]:
    """
    source_config: {
        location: "Austin, TX",                     # required — city, region, or "lat,lng"
        business_types: ["restaurant", "lawyer"],   # optional — filters search queries
        max_results: 30,                            # hard cap, default 30
    }
    """
    api_key = _api_key()
    if not api_key:
        log.error("google_places.no_api_key")
        return []

    location = source_config.get("location", "").strip()
    if not location:
        log.error("google_places.no_location")
        return []

    business_types = source_config.get("business_types", DEFAULT_BUSINESS_TYPES[:8])
    max_results = min(source_config.get("max_results", 30), 50)

    seen_ids: set[str] = set()
    no_website: list[dict] = []

    async with safe_client() as client:
        for btype in business_types:
            if len(no_website) >= max_results:
                break

            # Search this category in the target city
            it_fit = IT_SERVICE_FIT_MAP.get(btype, "needs digital infrastructure and IT support")
            search_query = btype.replace("_", " ")
            data = await _text_search(client, search_query, location)

            status = data.get("status", "")
            if status == "REQUEST_DENIED":
                log.error("google_places.api_denied", message=data.get("error_message"))
                break
            if status not in ("OK", "ZERO_RESULTS"):
                log.warning("google_places.bad_status", status=status, type=btype)
                continue

            candidates = data.get("results", [])
            log.info("google_places.search", type=btype, location=location, candidates=len(candidates))

            for candidate in candidates:
                if len(no_website) >= max_results:
                    break

                place_id = candidate.get("place_id", "")
                if not place_id or place_id in seen_ids:
                    continue
                seen_ids.add(place_id)

                # Check basic status
                if candidate.get("business_status") == "CLOSED_PERMANENTLY":
                    continue

                # Quick check: if Text Search result already has a website field, skip
                if candidate.get("website"):
                    continue

                # Fetch details to confirm no website
                detail = await _get_details(client, place_id)
                if not detail:
                    continue

                # Only keep businesses with no website
                if detail.get("website"):
                    continue

                # Skip permanently closed
                if detail.get("business_status") == "CLOSED_PERMANENTLY":
                    continue

                name = detail.get("name") or candidate.get("name", "")
                address = detail.get("formatted_address") or candidate.get("formatted_address", "")
                maps_url = detail.get("url") or f"https://www.google.com/maps/place/?q=place_id:{place_id}"
                ext_id = f"gplace-{hashlib.sha256(place_id.encode()).hexdigest()[:12]}"

                profile_text = _build_profile_text(detail, it_fit)
                types_raw = detail.get("types", candidate.get("types", []))

                no_website.append({
                    "platform": "google_places",
                    "external_id": ext_id,
                    "url": maps_url,
                    "title": name,
                    "text": profile_text,
                    "author_handle": place_id,
                    "author_display_name": name,
                    "author_platform": "google_places",
                    "posted_at": datetime.now(timezone.utc).isoformat(),
                    "raw_data": {
                        "place_id": place_id,
                        "name": name,
                        "address": address,
                        "phone": detail.get("formatted_phone_number") or detail.get("international_phone_number"),
                        "rating": detail.get("rating"),
                        "review_count": detail.get("user_ratings_total"),
                        "business_types": types_raw,
                        "category": btype,
                        "it_fit": it_fit,
                        "maps_url": maps_url,
                        "has_website": False,
                        "data_source": "google_places_api",
                        "attribution": "Powered by Google",
                    },
                })
                log.info("google_places.lead_found", name=name, address=address)

    log.info("google_places.done", found=len(no_website))
    return no_website

import re
import time
from datetime import datetime, timezone, timedelta

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, Request
from fetch_api.limiter import limiter

from db.mongo import get_async_db
from listings.shared.normalize import strip_html

router = APIRouter()

# Short-TTL in-memory cache for the dropdown endpoints
# (/api/locations, /api/sources). These run distinct() over
# ~49k jobs on every call and return data that only changes when ingestion
# runs (once a day) — a 5-minute stale window is invisible to users.
_DROPDOWN_CACHE: dict[str, tuple[float, object]] = {}
_DROPDOWN_TTL_SECONDS = 300


def _cache_get(key: str):
    entry = _DROPDOWN_CACHE.get(key)
    if entry and entry[0] > time.monotonic():
        return entry[1]
    return None


def _cache_set(key: str, value) -> None:
    _DROPDOWN_CACHE[key] = (time.monotonic() + _DROPDOWN_TTL_SECONDS, value)

_TAG_RE = re.compile(r"<[a-zA-Z/][^>]*>")

_SPAM_RE = re.compile(
    r"(?:please mention the word|tag [A-Za-z0-9+/=]{10,}|"
    r"this is a beta feature to avoid spam|"
    r"companies can search these words)",
    re.IGNORECASE,
)


def _clean_description(desc: str) -> str:
    if not desc:
        return desc
    if _TAG_RE.search(desc):
        desc = strip_html(desc)
    lines = desc.split("\n")
    cleaned = [l for l in lines if not _SPAM_RE.search(l)]
    return "\n".join(cleaned).strip()


def serialize_job(doc: dict, matched_skills: list[str] | None = None) -> dict:
    # Logo resolution — single source of truth, no guessing:
    #   1. Source-provided direct URL (RemoteOK's company_logo field)
    #   2. Google favicon of a source-provided real domain
    #   3. null → frontend renders a colored-letter fallback
    logo_url = doc.get("logo_url")
    if not logo_url:
        domain = doc.get("company_domain")
        if domain:
            logo_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"

    title = doc.get("title", "")
    location = doc.get("location", "Not specified")
    desc = _clean_description(doc.get("description", ""))
    # work_type, experience_level, and required_skills are now strictly guaranteed by ingestion.
    work_type = doc.get("work_type")
    experience = doc.get("experience_level")
    required_skills = doc.get("required_skills", [])
    
    posted_at = doc.get("posted_at")
    
    job = {
        "id": str(doc["_id"]),
        "title": title,
        "company": doc.get("company", ""),
        "location": location,
        "description": desc,
        "applyUrl": doc.get("apply_url", ""),
        "postedAt": posted_at.isoformat() if isinstance(posted_at, datetime) else posted_at,
        "source": doc.get("source", ""),
        "workType": work_type,
        "experience": experience,
        "requiredSkills": required_skills,
        "logoUrl": logo_url,
    }
    if matched_skills is not None:
        job["matchedSkills"] = matched_skills
    return job


def _split_param(val: str, sep: str = r"[,|]") -> list[str]:
    return [s.strip() for s in re.split(sep, val) if s.strip()]


_TOKEN_SPLIT_RE = re.compile(r"[;,]\s*")


def _tokenize_query_location(raw: str) -> list[str]:
    """Same tokenization storage.py uses at ingest time — kept in sync so
    the user's picked value ("Bengaluru, India") produces the exact tokens
    stored on each job ("bengaluru", "india")."""
    seen: set[str] = set()
    tokens: list[str] = []
    for part in _TOKEN_SPLIT_RE.split(raw):
        part = part.strip().lower()
        if part and part not in seen:
            seen.add(part)
            tokens.append(part)
    return tokens


def _location_branch(raw: str) -> dict:
    """Build the Mongo query fragment for one location selection.

    Fast path: match indexed `location_tokens` with $all — every token the
    user picked must appear on the job.

    Legacy fallback: pre-2026-08-14 docs have no `location_tokens` field.
    They still match if their raw `location` contains the selection as a
    substring (case-insensitive). This branch dies naturally as ingestion
    cycles those docs through re-save (or run
    pipeline/archive/backfill_location_tokens.py to accelerate). Once every
    doc has tokens the fallback is dead code and safe to remove.
    """
    tokens = _tokenize_query_location(raw)
    if not tokens:
        return {}
    return {
        "$or": [
            {"location_tokens": {"$all": tokens}},
            {
                "location_tokens": {"$exists": False},
                "location": {"$regex": re.escape(raw), "$options": "i"},
            },
        ]
    }


def _merge_location_branch(filt: dict, and_clauses: list, branch: dict) -> None:
    """A location branch is already `{$or: [...]}`. Append it to the
    top-level $and container we're building so it composes cleanly with
    the posted-date $or (see the `posted` handler below)."""
    if branch:
        and_clauses.append(branch)


def _posted_cutoff(posted: str):
    mapping = {"today": 1, "week": 7, "month": 30}
    days = mapping.get(posted)
    if days is None:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def _build_filter(
    source: str | None,
    location: str | None,
    work_type: str | None = None,
    experience: str | None = None,
    posted: str | None = None,
) -> dict:
    filt = {}
    # Any clause needing its own $or is collected here and emitted as a single
    # $and. Assigning filt["$or"] directly means the second such clause
    # silently overwrites the first — both location and posted need one.
    and_clauses: list[dict] = []

    if source:
        vals = _split_param(source)
        if vals:
            filt["source"] = {"$in": vals} if len(vals) > 1 else vals[0]
    if location:
        vals = _split_param(location, sep=r"\|")
        if vals:
            branches = [_location_branch(v) for v in vals]
            if len(branches) == 1:
                # A single selection may itself have multiple compound tokens
                # (e.g. "Bengaluru, India" → both must match). That $and lives
                # inside branches[0]; merge into the top-level and_clauses.
                _merge_location_branch(filt, and_clauses, branches[0])
            else:
                and_clauses.append({"$or": branches})
    if work_type:
        vals = _split_param(work_type)
        if vals:
            filt["work_type"] = {"$in": vals} if len(vals) > 1 else vals[0]
    if experience:
        vals = _split_param(experience)
        if vals:
            filt["experience_level"] = {"$in": vals} if len(vals) > 1 else vals[0]
    if posted:
        cutoff = _posted_cutoff(posted)
        if cutoff:
            # Lever doesn't expose a post date, so its jobs store posted_at as
            # None — and {"$gte": cutoff} never matches null. Filtering on
            # posted_at alone made every Lever job disappear the moment a user
            # picked any Posted option. For undated jobs we fall back to
            # added_at (when we first ingested it), which is a fair proxy for
            # "new" and is indexed.
            and_clauses.append({
                "$or": [
                    {"posted_at": {"$gte": cutoff}},
                    {"posted_at": None, "added_at": {"$gte": cutoff}},
                ]
            })

    if and_clauses:
        filt["$and"] = and_clauses
    return filt


# Server-side sort resolver. Named modes match SortControl.jsx values.
# `_id` is always appended as a stable tiebreaker so pagination doesn't
# duplicate or skip rows when two jobs share a sort key.
_NEWEST_SORT  = [("posted_at",    -1), ("_id", 1)]
# Sort on `company_sort` — a normalized key set at ingest that strips leading
# punctuation. Prevents "*Strello Health" / ". Crane" rows from hijacking the
# top of the A-Z list ahead of real "A..." companies.
_COMPANY_SORT = [("company_sort",  1), ("_id", 1)]


def _resolve_find_sort(sort: str | None, has_skills: bool) -> list[tuple[str, int]]:
    """Sort for `.find()` — the no-skills branch of /api/matches, and the
    tokenless branch of /api/search."""
    if sort == "company":
        return _COMPANY_SORT
    # "relevance" is meaningless without a ranking signal — fall through
    # to newest so the URL still yields a sensible order.
    return _NEWEST_SORT


def _resolve_agg_sort(sort: str | None, default: dict) -> dict:
    """Sort stage for aggregation `$facet` branches. `default` is the
    endpoint's own ranking (match_count for /matches, title/skill hits for
    /search). Overridden only for explicit newest / company requests."""
    if sort == "company":
        return {"company_sort": 1, "_id": 1}
    if sort == "newest":
        return {"posted_at": -1, "_id": 1}
    return default


@router.get("/api/matches")
@limiter.limit("30/minute")
async def get_matches(
    request: Request,
    limit: int = Query(50, ge=1, le=1000),
    skip: int = Query(0, ge=0),
    skills: str = Query(None, description="Comma-separated skills to rank matches by"),
    source: str = Query(None),
    location: str = Query(None),
    type: str = Query(None, description="Comma-separated work types (Remote/Hybrid/On-site)"),
    experience: str = Query(None, description="Comma-separated experience levels"),
    posted: str = Query(None, description="Date range: today, week, or month"),
    sort: str = Query(None, description="relevance (default with skills), newest, or company"),
):
    db = get_async_db()
    skill_list = [s.strip() for s in skills.split(",") if s.strip()] if skills else []
    base_filter = _build_filter(source, location, type, experience, posted)

    if not skill_list:
        total = await db.jobs.count_documents(base_filter)
        # `.limit(limit)` is required — `to_list(length=…)` is only a batch
        # size hint in Motor, not a cursor cap, so without .limit() page 2
        # (skip=15) silently returns every remaining row instead of 15.
        docs = await db.jobs.find(base_filter).sort(_resolve_find_sort(sort, has_skills=False)).skip(skip).limit(limit).to_list(length=limit)
        return {
            "jobs": [serialize_job(doc) for doc in docs],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    # $text is a loose fuzzy match (stemming), so it can surface jobs that
    # share only a common English word (e.g. "storage", "design"). Require
    # at least one skill to appear as a real substring in title/description
    # before returning the job — otherwise a Go-only role can leak into a
    # React/Python match list because its description says "storage".
    scored_stage = [
        {"$match": {**base_filter, "$text": {"$search": " ".join(skill_list)}}},
        {"$addFields": {
            "matched_skills": {
                "$filter": {
                    "input": skill_list,
                    "as": "skill",
                    "cond": {
                        "$or": [
                            {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$title", ""]}}, {"$toLower": "$$skill"}]}, 0]},
                            {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$description", ""]}}, {"$toLower": "$$skill"}]}, 0]}
                        ]
                    }
                }
            }
        }},
        {"$addFields": {"match_count": {"$size": "$matched_skills"}}},
        {"$match": {"match_count": {"$gte": 1}}},
    ]

    facet_stage = {
        "$facet": {
            "docs": [
                {"$sort": _resolve_agg_sort(sort, {"match_count": -1, "last_seen_at": -1, "_id": 1})},
                {"$skip": skip},
                {"$limit": limit},
            ],
            "total": [{"$count": "value"}],
        }
    }

    facet = await db.jobs.aggregate(scored_stage + [facet_stage], allowDiskUse=True).to_list(length=1)
    result = facet[0] if facet else {"docs": [], "total": []}
    docs = result["docs"]
    total = result["total"][0]["value"] if result["total"] else 0

    return {
        "jobs": [serialize_job(doc, doc.get("matched_skills", [])) for doc in docs],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/api/search")
@limiter.limit("30/minute")
async def search_jobs(
    request: Request,
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(15, ge=1, le=200),
    skip: int = Query(0, ge=0),
    source: str = Query(None),
    location: str = Query(None),
    type: str = Query(None),
    experience: str = Query(None),
    posted: str = Query(None),
    sort: str = Query(None, description="relevance (default), newest, or company"),
):
    db = get_async_db()
    base_filter = _build_filter(source, location, type, experience, posted)

    # Tokenize the query for title-anchored matching.
    tokens = re.findall(r"[a-z0-9+#.]+", q.lower())
    if not tokens:
        query = {**base_filter, "$text": {"$search": q}}
        total = await db.jobs.count_documents(query)
        docs = await db.jobs.find(query).sort(_resolve_find_sort(sort, has_skills=False)).skip(skip).limit(limit).to_list(length=limit)
        return {
            "jobs": [serialize_job(doc) for doc in docs],
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    # Ranking rules:
    #   - At least one query token must appear in the title OR in the job's
    #     required_skills list. Description-only hits are noise ("developer"
    #     mentioned in a Customer Relationship Manager paragraph).
    #   - For 3+ word queries, require a majority of tokens somewhere in
    #     title/skills so we don't over-tighten multi-word searches.
    min_total_matches = 1 if len(tokens) <= 2 else max(2, len(tokens) - 1)

    # Reusable Mongo expression: does the input token appear (case-insensitive)
    # as a substring in any element of $required_skills?
    def _token_in_skills():
        return {
            "$anyElementTrue": {
                "$map": {
                    "input": {"$ifNull": ["$required_skills", []]},
                    "as": "sk",
                    "in": {"$gte": [{"$indexOfCP": [{"$toLower": "$$sk"}, {"$toLower": "$$token"}]}, 0]}
                }
            }
        }

    scored_stage = [
        {"$match": {**base_filter, "$text": {"$search": q}}},
        {"$addFields": {
            "score": {"$meta": "textScore"},
            "title_hits": {
                "$size": {
                    "$filter": {
                        "input": tokens,
                        "as": "token",
                        "cond": {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$title", ""]}}, {"$toLower": "$$token"}]}, 0]}
                    }
                }
            },
            "skill_hits": {
                "$size": {
                    "$filter": {
                        "input": tokens,
                        "as": "token",
                        "cond": _token_in_skills()
                    }
                }
            },
            "total_hits": {
                "$size": {
                    "$filter": {
                        "input": tokens,
                        "as": "token",
                        "cond": {
                            "$or": [
                                {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$title", ""]}}, {"$toLower": "$$token"}]}, 0]},
                                _token_in_skills(),
                            ]
                        }
                    }
                }
            }
        }},
        # Must match title OR skills (not description). And enough tokens total.
        {"$match": {"total_hits": {"$gte": min_total_matches}}},
    ]

    facet_stage = {
        "$facet": {
            "docs": [
                {"$sort": _resolve_agg_sort(sort, {"title_hits": -1, "skill_hits": -1, "total_hits": -1, "score": -1, "_id": 1})},
                {"$skip": skip},
                {"$limit": limit},
            ],
            "total": [{"$count": "value"}],
        }
    }

    facet = await db.jobs.aggregate(scored_stage + [facet_stage], allowDiskUse=True).to_list(length=1)
    result = facet[0] if facet else {"docs": [], "total": []}
    docs = result["docs"]
    total = result["total"][0]["value"] if result["total"] else 0

    if not docs and skip == 0:
        # Fallback: same rule but only require ANY token to hit title or skills
        # (drops the min_total_matches gate). Description matches still excluded.
        fb_stage = [
            {"$match": {**base_filter, "$text": {"$search": q}}},
            {"$addFields": {
                "score": {"$meta": "textScore"},
                "title_hits": {
                    "$size": {
                        "$filter": {
                            "input": tokens,
                            "as": "token",
                            "cond": {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$title", ""]}}, {"$toLower": "$$token"}]}, 0]}
                        }
                    }
                },
                "skill_hits": {
                    "$size": {
                        "$filter": {
                            "input": tokens,
                            "as": "token",
                            "cond": _token_in_skills()
                        }
                    }
                },
            }},
            {"$match": {"$or": [{"title_hits": {"$gte": 1}}, {"skill_hits": {"$gte": 1}}]}},
        ]
        fb_facet = {
            "$facet": {
                "docs": [
                    {"$sort": _resolve_agg_sort(sort, {"title_hits": -1, "skill_hits": -1, "score": -1, "_id": 1})},
                    {"$skip": skip},
                    {"$limit": limit},
                ],
                "total": [{"$count": "value"}],
            }
        }
        fb = await db.jobs.aggregate(fb_stage + [fb_facet], allowDiskUse=True).to_list(length=1)
        fb_result = fb[0] if fb else {"docs": [], "total": []}
        docs = fb_result["docs"]
        total = fb_result["total"][0]["value"] if fb_result["total"] else 0

    return {
        "jobs": [serialize_job(doc) for doc in docs],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


# Countries that scrapers write in multiple string forms. Normalized so
# "USA", "U.S.A.", "United States of America" all fold into one dropdown row.
_COUNTRY_ALIASES = {
    "usa": "United States",
    "u.s.a.": "United States",
    "u.s.": "United States",
    "us": "United States",
    "united states of america": "United States",
    "america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "great britain": "United Kingdom",
    "gb": "United Kingdom",
    "uae": "United Arab Emirates",
    "u.a.e.": "United Arab Emirates",
}

# Country names, canonical form. Used to detect entries where the first
# comma-part is a country (reversed "Country, City" order — junk).
_KNOWN_COUNTRIES = {
    "united states", "united kingdom", "united arab emirates",
    "canada", "india", "germany", "france", "spain", "italy",
    "netherlands", "belgium", "sweden", "norway", "denmark", "finland",
    "poland", "portugal", "ireland", "australia", "new zealand",
    "singapore", "japan", "south korea", "china", "hong kong", "taiwan",
    "brazil", "argentina", "mexico", "colombia", "chile", "peru",
    "israel", "south africa", "egypt", "nigeria", "kenya", "morocco",
    "philippines", "indonesia", "malaysia", "thailand", "vietnam",
    "pakistan", "bangladesh", "sri lanka", "turkey", "russia", "ukraine",
    "romania", "czech republic", "hungary", "austria", "switzerland",
    "greece", "estonia", "latvia", "lithuania", "bulgaria", "slovakia",
    "slovenia", "croatia", "serbia", "iceland", "malta", "luxembourg",
    "cyprus", "afghanistan", "saudi arabia", "qatar", "kuwait", "bahrain",
    "oman", "jordan", "lebanon", "iceland",
}

# Rejected outright — work-type words, not places.
_WORK_TYPE_WORDS = {
    "remote", "hybrid", "onsite", "on-site", "on site",
    "anywhere", "worldwide", "flexible", "n/a", "na",
}

# Strip work-type prefixes off the raw location before we parse it as
# geography. Handles "Remote — United States", "Remote (India)",
# "Hybrid / London", "Onsite: Berlin".
_WORK_TYPE_PREFIX_RE = re.compile(
    r"^\s*(?:remote|hybrid|on[-\s]?site|onsite|fully\s+remote)"
    r"\s*[—\-\(\)/:,]+\s*",
    re.IGNORECASE,
)

# Junk we never want to display as a location option: URLs, HTML entities,
# code brackets, marketing prefixes, multi-region joiners like " / " and
# " & ", and Adzuna-style source codes like "US.VA.RESTON".
_LOC_JUNK_RE = re.compile(
    r"https?://|\.com\b|\.net\b|\.io\b|\.dev\b|&#|&amp|&quot|&lt|&gt"
    r"|[*{}\[\]?!]"
    r"|[/&|]|\bor\b|\.{2,}"
    r"|^[A-Z]{2,4}\.[A-Z]{2,}",
    re.IGNORECASE,
)

# Words that mean the raw string is a job title, marketing text, or a
# generic placeholder rather than a place.
_NOT_A_PLACE_WORDS = {
    "engineer", "developer", "designer", "manager", "analyst", "scientist",
    "specialist", "consultant", "architect", "lead", "director",
    "product", "senior", "junior", "intern", "software",
    "multiple", "various", "any", "all", "here", "add", "posting",
}


def _titlecase_place(part: str) -> str:
    """'united states' → 'United States'. Preserves uppercase acronyms
    ('USA', 'UK') and existing 2-letter state codes ('CA', 'NY')."""
    if not part:
        return part
    # Country alias first — canonicalizes "usa" → "United States" etc.
    lower = part.strip().lower()
    if lower in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[lower]
    upper_words = {"usa", "uk", "uae", "eu"}
    out = []
    for w in part.split():
        wl = w.lower()
        if wl in upper_words:
            out.append(w.upper())
        elif len(w) == 2 and w.isalpha() and w.isupper():
            out.append(w)  # keep state codes like "CA", "NY"
        else:
            out.append(w.capitalize())
    return " ".join(out)


def _clean_location_display(raw: str) -> str | None:
    """Turn a raw scraped location into a clean 'City, Country' string, or
    None to drop. Rejects addresses, work-type-only strings, and junk."""
    if not raw:
        return None
    s = raw.strip()
    # Strip leading "Remote — ", "Hybrid / ", "Onsite: " prefixes AND leading
    # noise like brackets, quotes, dollar signs, slashes.
    prev = None
    while prev != s:
        prev = s
        s = _WORK_TYPE_PREFIX_RE.sub("", s).strip(" -—:()/,\"'`$#~|\\")
    if not s or len(s) < 2 or len(s) > 80:
        return None
    if _LOC_JUNK_RE.search(s):
        return None
    # Reject street addresses / marketing counts ("1530 FM 973 Taylor",
    # "10 Locations", "100% Remote") — never a real place name.
    if s[0].isdigit():
        return None
    # First character must be an ASCII letter — anything else is junk
    # fragments like "$175", "/^full", "√ Remote", or CJK/mojibake noise.
    if not ('a' <= s[0].lower() <= 'z'):
        return None
    # If the string reads like a job title / marketing placeholder rather
    # than a place, drop it. Checks whole-word matches to avoid killing
    # real names ("Product Way" the street would be gone, but so would
    # "AI Product Engineer" the job title — the latter is far more common).
    low = s.lower()
    if any(re.search(rf"\b{re.escape(w)}\b", low) for w in _NOT_A_PLACE_WORDS):
        return None
    # Catch scraper mishaps where "Remote" was concatenated straight into
    # description text ("Remotelegion Is Building A Platform..."). The
    # earlier work-type check requires a word boundary; this one doesn't.
    for prefix in ("remote", "hybrid", "onsite"):
        if low.startswith(prefix) and (len(s) == len(prefix) or not s[len(prefix)].isspace()):
            # Real place would have a space or punctuation after; if the
            # next char is another letter, it's fused garbage.
            if len(s) > len(prefix) and s[len(prefix)].isalpha():
                return None
    # Sentence-like entries are never place names. Real "City, State,
    # Country" caps out around 6 words; anything longer is description text.
    if len(s.split()) > 6:
        return None
    if s.lower() in _WORK_TYPE_WORDS:
        return None
    # Reject entries whose lower-case body contains work-type words —
    # "Remote India", "Chicago Or Remote", "Hybrid Or Remote", "Onsite/hybrid"
    # are all noise, not places we want in the dropdown. Real cities named
    # "Remote" or "Hybrid" don't exist.
    low = s.lower()
    if any(re.search(rf"\b{re.escape(w)}\b", low) for w in _WORK_TYPE_WORDS):
        return None
    # Split into comma parts. Common shapes:
    #   "Chicago, IL"                    → City, State
    #   "Bengaluru, India"               → City, Country
    #   "Chicago, IL, USA"               → City, State, Country
    #   "Chicago, IL, United States"     → City, State, Country
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if not parts:
        return None
    # Any single part that's itself a work-type word gets dropped.
    parts = [p for p in parts if p.lower() not in _WORK_TYPE_WORDS]
    if not parts:
        return None
    # Normalize each part (country aliases + case).
    parts = [_titlecase_place(p) for p in parts]
    # Reject reversed-order entries where the FIRST part is a country name
    # ("United States, Atlanta", "Afghanistan, United Arab Emirates",
    # "United States, India" — dual-country blobs or bad ordering). Real
    # "City, Country" always has the city first.
    if parts[0].lower() in _KNOWN_COUNTRIES and len(parts) > 1:
        # Single-country entries would have `len(parts) == 1` and never hit
        # this branch, so "United States" alone still passes.
        return None
    # Prefer City + Country (first + last) when we have 3+ parts, so
    # "Chicago, IL, United States" collapses with "Chicago, United States"
    # instead of leaking a separate "Chicago, IL, United States" row.
    if len(parts) >= 3:
        return f"{parts[0]}, {parts[-1]}"
    if len(parts) == 2:
        return f"{parts[0]}, {parts[1]}"
    return parts[0]


@router.get("/api/locations")
@limiter.limit("10/minute")
async def get_locations(request: Request):
    """Dropdown source. Deduped, work-type-free, formatted as 'City, Country'
    (or 'City' / 'Country' alone when that's all the source gave us).
    Backed by the raw `location` field with heavy cleaning — using
    `location_tokens` loses the city-country pairing since it's a flat array."""
    cached = _cache_get("locations")
    if cached is not None:
        return cached

    db = get_async_db()
    raw_values = [v for v in await db.jobs.distinct("location") if v and v.strip()]
    seen: set[str] = set()
    for raw in raw_values:
        # Some sources join multiple locations with ";" — split those out.
        for chunk in raw.split(";"):
            cleaned = _clean_location_display(chunk)
            if cleaned:
                seen.add(cleaned)
    # Dedupe city-only rows when a "city, country" form of the same city
    # exists — e.g. drop "Las Vegas" if "Las Vegas, United States" is present.
    # But keep single-token COUNTRIES like "United States" alone: something
    # is a country (not a city being deduped) if it also shows up as the
    # last comma-part of another entry.
    first_parts = {v.split(",")[0].strip().lower() for v in seen if "," in v}
    last_parts  = {v.split(",")[-1].strip().lower() for v in seen if "," in v}
    city_only = first_parts - last_parts
    seen = {v for v in seen if "," in v or v.strip().lower() not in city_only}
    result = sorted(seen)
    _cache_set("locations", result)
    return result


@router.get("/api/sources")
@limiter.limit("10/minute")
async def get_sources(request: Request):
    cached = _cache_get("sources")
    if cached is not None:
        return cached

    db = get_async_db()
    values = [v for v in await db.jobs.distinct("source") if v and v.strip()]
    result = sorted(values)
    _cache_set("sources", result)
    return result


@router.get("/api/jobs/{job_id}")
@limiter.limit("60/minute")
async def get_job(job_id: str, request: Request):
    try:
        oid = ObjectId(job_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid job id")

    db = get_async_db()
    doc = await db.jobs.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Job not found")

    return serialize_job(doc)

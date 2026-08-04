# Whofy API — Canonical Data Reference

> **Last verified:** 2026-08-04 against the live codebase and 33,895-document production database.
> Every claim in this document was pulled from actual source files and real database queries.
> Source of truth: [models/job.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/models/job.py)

---

## 1. Canonical Job Schema (`jobs` collection)

Pydantic model: `Job` in [models/job.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/models/job.py#L25-L71)

| MongoDB Field | Python Type | Required? | Constraints / Allowed Values | Description | Sources that may leave it `None` |
|---|---|---|---|---|---|
| `_id` | `ObjectId` | Auto | MongoDB auto-generated | Document primary key | N/A — auto-generated |
| `source` | `str` | **Required** | `min_length=1` | Identifier of the ingestion source (e.g. `"greenhouse"`, `"lever"`) | Never `None` |
| `source_job_id` | `str` | **Required** | `min_length=1` | Source-specific unique job identifier (e.g. `"gh_2080930"`, `"lv_008e0a44-..."`) | Never `None` |
| `title` | `str` | **Required** | `min_length=1` | Job title as provided by the source | Never `None` |
| `company` | `str` | **Required** | `min_length=1` | Company name as provided by the source | Never `None` |
| `location` | `str` | **Required** | `min_length=1` | Normalized location string (see §6 for normalization logic) | Never `None` |
| `apply_url` | `str` | **Required** | `min_length=1` | URL to apply for the job | Never `None` |
| `fingerprint` | `str` | **Required** | `min_length=1` | Cross-source dedup key, computed as `{source}\|\|{source_job_id}` lowercased and stripped of non-alphanumeric chars (except `\|`) | Never `None` — computed in `save_jobs()` |
| `posted_at` | `Optional[datetime]` | Optional | Native BSON Date or `null` | When the job was originally posted | **Lever** — always `None` (API doesn't expose it); flagged `missing_posted_at` |
| `added_at` | `datetime` | **Required** | Native BSON Date | When the job was first ingested into Whofy's database. Set via `$setOnInsert` so it never changes on re-scrape | Never `None` |
| `last_seen_at` | `datetime` | **Required** | Native BSON Date | Timestamp of the most recent scrape that encountered this job | Never `None` |
| `data_quality_flags` | `List[DataQualityFlag]` | Required | `[]` or list of: `"missing_posted_at"`, `"missing_description"` | Flags indicating known data gaps for this document | Empty for all sources except Lever (`missing_posted_at`) and Workday (`missing_description`) |
| `description` | `Optional[str]` | Optional | Normalized: empty string / whitespace → `None` via `@field_validator` | Job description text, with enriched "Required skills:" block appended | **Workday** — always `None` (API doesn't return descriptions); flagged `missing_description` |
| `company_domain` | `Optional[str]` | Optional | Normalized: empty string / whitespace → `None` via `@field_validator` | Company's web domain (e.g. `"spotify.com"`) | **Adzuna**, **RemoteOK**, **WeWorkRemotely** — never provide it. HackerNews provides it when parseable from the post. Others provide it from their APIs. |
| `required_skills` | `List[str]` | **Required** | Max 15 entries. Values are canonical skill names from `SKILL_VOCAB` | Skills extracted from title + description via regex matching | Never `None` — always populated (may be `[]` if nothing matched) |
| `work_type` | `Literal["Remote", "Hybrid", "On-site"]` | **Required** | Exactly one of three values | Detected from title, location, and description text | Never `None` — defaults to `"On-site"` if no signal detected |
| `experience_level` | `str` | **Required** | `min_length=1`. Values: `"Internship"`, `"Entry Level"`, `"Junior"`, `"Mid Level"`, `"Senior"` | Detected from title and description via regex | Never `None` — defaults to `"Mid Level"` if no signal detected |
| `lang_checked` | `bool` | **Required** | `true` or `false` | Whether the job passed the English language filter | Never `None` — always set to `true` in `save_jobs()` |

### Indexes (verified against live `db.jobs.getIndexes()`)

| Index Name | Fields | Properties |
|---|---|---|
| `_id_` | `_id: 1` | Default |
| `source_1_source_job_id_1` | `source: 1, source_job_id: 1` | **Unique** |
| `posted_at_-1__id_1` | `posted_at: -1, _id: 1` | Compound sort |
| `last_seen_at_-1` | `last_seen_at: -1` | Expiry/staleness queries |
| `added_at_-1` | `added_at: -1` | Recency queries |
| `title_text_description_text` | `title: text, description: text` | Full-text search |
| `work_type_1` | `work_type: 1` | Filter |
| `experience_level_1` | `experience_level: 1` | Filter |

---

## 2. Per-Source Field Availability Matrix

Based on actual fetcher code inspection. Legend:
- ✅ = Always populated
- ⚠️ = Sometimes empty / `None`
- ❌ = Always `None` (flagged)

| Field | Greenhouse | Adzuna | Ashby | Lever | RemoteOK | Himalayas | Workday | WeWorkRemotely | HackerNews |
|---|---|---|---|---|---|---|---|---|---|
| `source` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `source_job_id` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `title` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `company` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `location` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `apply_url` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `posted_at` | ✅ | ✅ | ✅ | ❌ `missing_posted_at` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `description` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ `missing_description` | ✅ | ✅ |
| `company_domain` | ✅ | ⚠️ `None` | ✅ | ✅ | ⚠️ `None` | ✅ | ✅ | ⚠️ `None` | ⚠️ parsed from post |
| `required_skills` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `work_type` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `experience_level` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `data_quality_flags` | ✅ `[]` | ✅ `[]` | ✅ `[]` | ✅ `[missing_posted_at]` | ✅ `[]` | ✅ `[]` | ✅ `[missing_description]` | ✅ `[]` | ✅ `[]` |
| `fingerprint` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `lang_checked` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

### Notes
- **Enrichment fields** (`required_skills`, `work_type`, `experience_level`) are computed by the fetcher before `save_jobs()` is called, using `enrich.py` functions. They are never `None`.
- **`company_domain`**: Adzuna, RemoteOK, and WeWorkRemotely do not provide this field at all. The fetchers simply omit it from the dict, which means the `Job` model defaults it to `None`. HackerNews parses it from the post body when a URL is present.
- **`fingerprint`**: Computed inside `save_jobs()` in `storage.py`, not by the fetcher.
- **`lang_checked`**: Hardcoded to `True` inside `save_jobs()`.

---

## 3. SavedJob Schema (`saved_jobs` collection)

Pydantic model: `SavedJob` in [models/job.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/models/job.py#L78-L97)

| MongoDB Field | Python Type | Required? | Description |
|---|---|---|---|
| `_id` | `ObjectId` | Auto | Document primary key |
| `user_id` | `str` | **Required** | Clerk user ID (`sub` claim from JWT) |
| `job_id` | `ObjectId` | **Required** | Reference to the `_id` of the saved job in the `jobs` collection |
| `saved_at` | `datetime` | **Required** | Timestamp when the user saved this job |
| `snapshot` | `SavedJobSnapshot` (embedded) | **Required** | Frozen copy of the job's key fields at save time |

### SavedJobSnapshot (embedded sub-document)

Pydantic model: `SavedJobSnapshot` in [models/job.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/models/job.py#L73-L76)

| Field | Python Type | Required? | Description |
|---|---|---|---|
| `title` | `str` | **Required** | Job title at time of save |
| `company` | `str` | **Required** | Company name at time of save |
| `location` | `str` | **Required** | Location at time of save |

---

## 4. CompanyLogo Schema (`company_logos` collection)

Pydantic model: `CompanyLogo` in [models/job.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/models/job.py#L99-L110)

| MongoDB Field | Python Type | Required? | Description |
|---|---|---|---|
| `_id` | `ObjectId` | Auto | Document primary key |
| `company_key` | `str` | **Required** | Normalized company name (lowercase, alphanumeric only). Used as the lookup key. |
| `logo_url` | `Optional[str]` | Optional | Clearbit logo URL if found, `null` if not |

---

## 5. API Response Shapes

### Job Response (from `serialize_job()`)

Source: [fetch_api/jobs.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/fetch_api/jobs.py#L42-L76)

| JSON Response Field | Maps From DB Field | Type | Notes |
|---|---|---|---|
| `id` | `_id` | `string` | `str(doc["_id"])` |
| `title` | `title` | `string` | |
| `company` | `company` | `string` | |
| `location` | `location` | `string` | Falls back to `"Not specified"` |
| `description` | `description` | `string` | HTML-stripped and spam-filtered via `_clean_description()` |
| `applyUrl` | `apply_url` | `string` | |
| `postedAt` | `posted_at` | `string \| null` | `.isoformat()` if datetime, else raw value |
| `source` | `source` | `string` | |
| `workType` | `work_type` | `string` | One of `"Remote"`, `"Hybrid"`, `"On-site"` |
| `experience` | `experience_level` | `string` | |
| `requiredSkills` | `required_skills` | `string[]` | |
| `logoUrl` | derived | `string \| null` | Priority: `logo_url` from company_logos cache → Clearbit via `company_domain` → Google favicon via guessed domain |
| `matchedSkills` | computed | `string[]` | Only present in `/api/matches` when skills param is provided |

### Saved Job Response (from `/api/saved-jobs`)

Source: [fetch_api/saved_jobs.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/fetch_api/saved_jobs.py#L71-L111)

**If the original job still exists**, the response is the full `serialize_job()` shape above, plus:

| Additional Field | Maps From | Type | Notes |
|---|---|---|---|
| `savedAt` | `saved_jobs.saved_at` | `string` | `.isoformat()` |
| `expired` | computed | `boolean` | Always `false` |

**If the original job has been deleted** (expired), the response is a minimal shape:

| Field | Maps From | Type | Notes |
|---|---|---|---|
| `id` | `saved_jobs.job_id` | `string` | |
| `title` | `snapshot.title` | `string` | Falls back to `"Unknown role"` |
| `company` | `snapshot.company` | `string` | Falls back to `"Unknown company"` |
| `location` | `snapshot.location` | `string` | |
| `savedAt` | `saved_jobs.saved_at` | `string` | |
| `expired` | computed | `boolean` | Always `true` |

### Saved Job IDs Response (from `/api/saved-jobs/ids`)

Returns: `string[]` — array of `job_id` ObjectIds as strings.

---

## 6. Derived/Enrichment Fields — How They're Computed

### `required_skills`
- **Function:** `extract_required_skills(title, description)` in [enrich.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/listings/shared/enrich.py#L354-L373)
- **Inputs:** Job title + description concatenated
- **Logic:** Two-pass regex matching against `SKILL_VOCAB` (~961 terms). Pass 1: case-insensitive match via `_SKILL_PATTERN_CI` for skills NOT in `_CASE_SENSITIVE_SKILLS`. Pass 2: exact-case match via `_SKILL_PATTERN_CS` for short/ambiguous terms in `_CASE_SENSITIVE_SKILLS` (e.g. `"C"`, `"R"`, `"Go"`, `"V"`). Deduplicates and caps at 15 results.
- **Called by:** Each fetcher, during job dict construction, before passing to `save_jobs()`.

### `work_type`
- **Function:** `detect_work_type(title, location, description)` in [enrich.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/listings/shared/enrich.py#L302-L317)
- **Inputs:** Title, location, and first 500 chars of description
- **Logic:** Regex search for `remote`, `hybrid`, `on-site`/`in-office`/`in-person`. Checks title+location first, then description. Priority: Hybrid > Remote > On-site. Default: `"On-site"`.
- **Called by:** Each fetcher.

### `experience_level`
- **Function:** `detect_experience(title, description)` in [enrich.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/listings/shared/enrich.py#L320-L351)
- **Inputs:** Title and first 800 chars of description
- **Logic:** Checks title first for keywords (`intern`, `entry-level`, `junior`, `senior`, `staff`, `principal`, `lead`, `director`). Then parses `X+ years` from description to infer level (≤1yr → Entry, ≤3yr → Junior, ≤6yr → Mid, >6yr → Senior). Default: `"Mid Level"`.
- **Called by:** Each fetcher.

### `fingerprint`
- **Function:** `_fingerprint(source, source_job_id)` in [storage.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/listings/shared/storage.py#L35-L37)
- **Inputs:** Source name and source-specific job ID
- **Logic:** `f"{source}||{source_job_id}".lower()` then strip all non-`[a-z0-9|]` characters. Used for cross-source deduplication — if a fingerprint from source A already exists in source B, the job is skipped.
- **Called by:** `save_jobs()` in `storage.py`, not by fetchers.

### `lang_checked`
- **Set by:** `save_jobs()` in [storage.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/listings/shared/storage.py#L287)
- **Logic:** Hardcoded to `True` for all jobs that pass through `save_jobs()`. The non-English language filter (`_is_non_english()` using `langdetect`) was previously active but is currently bypassed (the filter call exists but `t_lang` is set immediately with no filtering between `t_old` and `t_lang`).

### `company_domain`
- **Set by:** Each fetcher that has access to the data. Adzuna, RemoteOK, and WeWorkRemotely do not set it (defaults to `None`).
- **Normalization:** The `Job` model's `@field_validator` converts empty strings and whitespace-only strings to `None`.
- **At API response time:** If `company_domain` is `None`, `serialize_job()` guesses a domain via `_guess_domain(company)` → `{slugified_company_name}.com` for the logo URL fallback only. This guess is **not** persisted back to the database.

### `location` (normalization)
- **Function:** `_normalize_location(raw)` in [storage.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/listings/shared/storage.py#L100-L199)
- **Called by:** `save_jobs()` before validation
- **Logic:** Splits raw location on `,`/`;`/`-`, maps tokens against `COUNTRY_CODE_MAP` and `KNOWN_CITIES` dictionaries. Outputs `"City, Country"` format when possible. Detects and preserves conflicting mappings (e.g. a city mapped to country A but another token maps to country B → returns the raw string unchanged to avoid "San Francisco, Canada"-type bugs).

---

## 7. Resume Parsing Data Points (separate, not stored)

Source: [parsing/resume_parser.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/parsing/resume_parser.py#L19-L29)

The resume parser uses Groq LLM (`openai/gpt-oss-120b`) with a JSON schema constraint. Output is returned directly to the frontend — **nothing is stored in MongoDB**.

| Field | JSON Type | Required? | Description |
|---|---|---|---|
| `skills` | `string[]` | **Required** | Technical/professional skills (max 15, most relevant first) |
| `location` | `string` | **Required** | Candidate's city, or `""` if not stated |
| `experienceLevel` | `string` | **Required** | Short phrase like `"Fresher"`, `"0-1 years"`, `"2-3 years"`, or `""` |
| `education` | `string[]` | **Required** | Degree/institution strings, most recent first |
| `summary` | `string` | **Required** | 1-2 sentence professional summary in third person |

### Resume Upload Constraints
- **Allowed formats:** `.pdf`, `.docx`
- **Max file size:** 10 MB
- **Text extraction:** PyMuPDF (PDF), python-docx (DOCX)
- **LLM input truncation:** First 15,000 characters of extracted text

---

## 8. User/Auth Data Points

Source: [fetch_api/auth.py](file:///c:/Users/chara/Desktop/whofy/whofy-api/fetch_api/auth.py#L54-L81)

The backend touches exactly **one** piece of user data:

| Data Point | Source | Storage | Description |
|---|---|---|---|
| `user_id` (`sub` claim) | Clerk JWT token | Stored in `saved_jobs.user_id` only | The Clerk user ID extracted from the verified JWT `sub` claim. Used to scope saved-jobs queries. |

**No other user data is captured or stored.** The backend does not store email, name, profile picture, or any other PII. Authentication is fully delegated to Clerk:
- JWKS endpoint: `https://api.clerk.com/v1/jwks` (authenticated with `CLERK_SECRET_KEY`)
- JWT verification: `jwt.decode(token, public_key, algorithms=["RS256"])` — full cryptographic signature verification
- Key rotation: Automatic retry on `kid` miss (clears JWKS cache and re-fetches)

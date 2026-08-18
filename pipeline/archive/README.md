# Spent one-shot migrations

These scripts each fixed a specific data problem once, against the live
`jobs` collection. Ingestion now writes the corrected values on every save,
so none of them need to run again — they are kept only as a record of what
was changed and why.

They still work if you ever restore an old snapshot, but **read the script
before running one**: they write directly to MongoDB and only
`fix_mojibake_bullets.py` defaults to a dry run.

| Script | Fixed | Now handled at write time by |
|---|---|---|
| `backfill_company_sort.py` | Populated `company_sort` so `*Strello Health` sorts under S | `storage.save_jobs` → `_normalize_company_sort` |
| `backfill_company_trim.py` | Stripped whitespace from `company` (a leading space sorted ahead of everything) | `storage.save_jobs` |
| `backfill_location_tokens.py` | Populated `location_tokens` for the indexed location filter | `storage.save_jobs` → `_tokenize_location` |
| `backfill_fingerprints.py` | Recomputed `fingerprint` after the dedup key changed | `storage.save_jobs` → `_fingerprint` |
| `fix_duplicate_skills.py` | Removed doubled "Required skills:" blocks from descriptions | `enrich.bake_required_skills` (no longer applied twice) |
| `fix_mojibake_bullets.py` | Rewrote `â€¢` to `•` in descriptions | `enrich.bake_required_skills` (encoding fixed at source) |

Still live, in `pipeline/`:

- `dedupe_jobs.py` — runs after every ingestion via GitHub Actions
- `canary.py` — weekly source health probe
- `cleanup.py` — manual retention run
- `audit_indexes.py` — manual index inspection
- `backfill_enrichment.py` — re-runs enrichment over the whole collection;
  not a one-shot, useful whenever the skill vocabulary or detection rules change

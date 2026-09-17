"""Single source of truth for how long a job lives in the system.

Every age cutoff in the codebase imports `RETENTION_DAYS` from here:

  - what the fetchers bother to request from each source
  - what the enrichment pipeline bothers to process
  - what storage deletes in cleanup_expired_jobs()

These three used to be separate constants and drifted apart to 30 / 28 / 14
respectively. The cost was silent and ongoing: fetchers pulled 30 days,
the pipeline paid for HTML stripping + skill regex + langdetect on
everything under 28 days, and storage then deleted everything over 14 —
so roughly half the enrichment work per run was thrown away seconds after
it was done. The chatbot separately told users "28 days", which was never
true.

Keep it one number. tests/test_retention.py asserts every consumer agrees.
"""

RETENTION_DAYS = 14

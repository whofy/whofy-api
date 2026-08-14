"""Tests for _build_filter — the translation layer from UI filter params to
a MongoDB query document.

Guards a few historical bugs:
  - `posted` used to filter on `posted_at` alone, which never matches null.
    Lever publishes no post date, so every Lever job vanished the moment a
    user picked any Posted option.
  - `$or` was written directly onto the filter dict, so a second clause
    needing `$or` would silently overwrite the first. Location and posted
    both need one.
  - `location` used a case-insensitive regex on an unindexed 65k-doc
    collection. It now uses indexed $all lookups against `location_tokens`
    with a fallback for pre-backfill docs.
"""
from datetime import datetime

from fetch_api.jobs import _build_filter


def _location_tokens_used(branch):
    """Extract the primary $all token list from a location branch."""
    for clause in branch.get("$or", []):
        if "location_tokens" in clause and "$all" in clause["location_tokens"]:
            return clause["location_tokens"]["$all"]
    return None


def test_empty_params_produce_empty_filter():
    assert _build_filter(None, None) == {}


def test_single_source_is_scalar_multi_is_in():
    assert _build_filter("lever", None)["source"] == "lever"
    assert _build_filter("lever|ashby", None)["source"] == {"$in": ["lever", "ashby"]}


def test_single_location_tokenizes_and_uses_all_on_indexed_field():
    filt = _build_filter(None, "Bengaluru, India")
    branch = filt["$and"][0]
    tokens = _location_tokens_used(branch)
    assert tokens == ["bengaluru", "india"], "compound location must produce both tokens"


def test_single_location_keeps_legacy_regex_fallback_for_pre_backfill_docs():
    """Backfill script populates location_tokens on old docs. Until that
    runs, the fallback branch keeps results correct — just slower for
    those specific docs. Once backfill is done the fallback is dead code."""
    filt = _build_filter(None, "Bengaluru, India")
    branches = filt["$and"][0]["$or"]

    fallback = next(b for b in branches if "location" in b)
    assert fallback["location_tokens"] == {"$exists": False}
    assert "$regex" in fallback["location"]


def test_location_splits_on_pipe_only_so_city_commas_survive():
    """"Bengaluru, India" must stay one value — splitting on comma would
    produce two broken fragments that match nothing."""
    filt = _build_filter(None, "Bengaluru, India|Remote")
    # Two selections → wrapped in $or.
    outer = filt["$and"][0]["$or"]
    assert len(outer) == 2

    token_sets = [_location_tokens_used(b) for b in outer]
    assert ["bengaluru", "india"] in token_sets
    assert ["remote"] in token_sets


def test_work_type_and_experience_map_to_their_mongo_fields():
    filt = _build_filter(None, None, "Remote", "Junior")
    assert filt["work_type"] == "Remote"
    assert filt["experience_level"] == "Junior"

    filt = _build_filter(None, None, "Remote|Hybrid", "Junior|Senior")
    assert filt["work_type"] == {"$in": ["Remote", "Hybrid"]}
    assert filt["experience_level"] == {"$in": ["Junior", "Senior"]}


def test_posted_keeps_undated_jobs_via_added_at_fallback():
    """Regression: filtering on posted_at alone hid every Lever job."""
    filt = _build_filter(None, None, posted="week")
    branches = filt["$and"][0]["$or"]

    assert len(branches) == 2
    assert isinstance(branches[0]["posted_at"]["$gte"], datetime)
    # Undated jobs survive, judged by when we first ingested them.
    assert branches[1]["posted_at"] is None
    assert isinstance(branches[1]["added_at"]["$gte"], datetime)


def test_unknown_posted_value_is_ignored():
    assert _build_filter(None, None, posted="yesteryear") == {}


def test_multi_location_and_posted_coexist():
    """Regression: both need $or. Writing $or directly onto the filter meant
    the second one silently erased the first."""
    filt = _build_filter(None, "Remote|Berlin, Germany", posted="today")

    assert "$or" not in filt, "clauses must be nested under $and, not top-level $or"
    assert len(filt["$and"]) == 2, "location and posted must BOTH survive"

    # One clause holds the two-branch location $or (each branch itself an
    # $or of fast/fallback), the other holds the posted-date $or. Walk the
    # tree looking for either shape.
    def _any_key_in(node, key):
        if isinstance(node, dict):
            if key in node:
                return True
            return any(_any_key_in(v, key) for v in node.values())
        if isinstance(node, list):
            return any(_any_key_in(v, key) for v in node)
        return False

    assert _any_key_in(filt["$and"], "location_tokens"), "location branch missing"
    assert _any_key_in(filt["$and"], "posted_at"), "posted branch missing"


def test_all_filters_together():
    filt = _build_filter("lever|ashby", "Remote|Pune, India", "Hybrid", "Senior", "month")

    assert filt["source"] == {"$in": ["lever", "ashby"]}
    assert filt["work_type"] == "Hybrid"
    assert filt["experience_level"] == "Senior"
    assert len(filt["$and"]) == 2

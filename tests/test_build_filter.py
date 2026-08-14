"""Tests for _build_filter — the translation layer from UI filter params to
a MongoDB query document.

Guards two bugs fixed on 2026-08-14:
  - `posted` used to filter on `posted_at` alone, which never matches null.
    Lever publishes no post date, so every Lever job vanished the moment a
    user picked any Posted option.
  - `$or` was written directly onto the filter dict, so a second clause
    needing `$or` would silently overwrite the first. Location and posted
    both need one.
"""
from datetime import datetime

from fetch_api.jobs import _build_filter


def test_empty_params_produce_empty_filter():
    assert _build_filter(None, None) == {}


def test_single_source_is_scalar_multi_is_in():
    assert _build_filter("lever", None)["source"] == "lever"
    assert _build_filter("lever|ashby", None)["source"] == {"$in": ["lever", "ashby"]}


def test_single_location_uses_regex_without_and():
    filt = _build_filter(None, "Bengaluru, India")
    assert filt["location"] == {"$regex": "Bengaluru,\\ India", "$options": "i"}
    assert "$and" not in filt


def test_location_splits_on_pipe_only_so_city_commas_survive():
    """"Bengaluru, India" must stay one value — splitting on comma would
    produce two broken fragments that match nothing."""
    filt = _build_filter(None, "Bengaluru, India|Remote")
    clauses = filt["$and"][0]["$or"]
    assert len(clauses) == 2
    assert "Bengaluru" in clauses[0]["location"]["$regex"]
    assert "India" in clauses[0]["location"]["$regex"]


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

    keys_per_clause = [set(k for b in c["$or"] for k in b) for c in filt["$and"]]
    assert {"location"} in keys_per_clause
    assert any("posted_at" in keys for keys in keys_per_clause)


def test_all_filters_together():
    filt = _build_filter("lever|ashby", "Remote|Pune, India", "Hybrid", "Senior", "month")

    assert filt["source"] == {"$in": ["lever", "ashby"]}
    assert filt["work_type"] == "Hybrid"
    assert filt["experience_level"] == "Senior"
    assert len(filt["$and"]) == 2

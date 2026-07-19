import re

_WORD_RE = re.compile(r"[a-z0-9+#.]+")


def rank_by_skills(candidates: list[dict], skill_list: list[str]) -> list[tuple[dict, list[str]]]:
    """
    Given a list of candidate job documents and a list of requested skills,
    computes which skills are matched in each job and sorts them.
    
    Sorting rules:
      1. Primary: Number of matched skills (descending)
      2. Secondary: Recency (last_seen_at) (descending)
      
    Returns a sorted list of tuples: (job_doc, matched_skills_list)
    """
    scored = []
    for doc in candidates:
        haystack = f"{doc.get('title', '')} {doc.get('description', '')}".lower()
        matched = [s for s in skill_list if s.lower() in haystack]
        scored.append((doc, matched))

    # Sort by recency first, then stable sort by match count
    scored.sort(key=lambda pair: pair[0].get("last_seen_at") or "", reverse=True)
    scored.sort(key=lambda pair: len(pair[1]), reverse=True)

    return scored


def rank_by_search_query(candidates: list[dict], query: str) -> list[dict]:
    """
    Given a list of candidate job documents from a $text search and the raw query,
    enforces a stricter token match than MongoDB's raw OR behavior.
    
    Sorting rules:
      1. Primary: Title hits
      2. Secondary: Total hits (title + description)
      3. Tertiary: Original text score from MongoDB
      
    Returns a sorted list of job_docs that meet the minimum match threshold.
    """
    tokens = _WORD_RE.findall(query.lower())
    if not tokens:
        return candidates

    min_matches = len(tokens) if len(tokens) <= 3 else len(tokens) - 1

    scored = []
    for doc in candidates:
        title_l = doc.get("title", "").lower()
        text_l = f"{title_l} {doc.get('description', '').lower()}"
        title_hits = sum(1 for t in tokens if t in title_l)
        total_hits = sum(1 for t in tokens if t in text_l)
        
        if total_hits < min_matches:
            continue
            
        scored.append((doc, title_hits, total_hits, doc.get("score", 0)))

    if not scored:
        # Nothing hit the strict bar (e.g. a typo) — fall back to raw ranking
        return candidates

    scored.sort(key=lambda t: (t[1], t[2], t[3]), reverse=True)
    return [t[0] for t in scored]

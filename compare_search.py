import asyncio
import re
from db.mongo import get_db, get_async_db

_WORD_RE = re.compile(r"[a-z0-9+#.]+")

def rank_by_search_query(candidates: list[dict], query: str) -> list[dict]:
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
        return candidates

    scored.sort(key=lambda t: (t[1], t[2], t[3]), reverse=True)
    return [t[0] for t in scored]

async def run_comparison():
    db_sync = get_db()
    db_async = get_async_db()
    
    q = "senior python backend developer"
    limit = 50
    
    # Check if there are any jobs in the DB at all to avoid errors
    if db_sync.jobs.count_documents({}) == 0:
        print("No jobs in database to test with.")
        return

    # OLD LOGIC
    fetch_limit = max(limit * 5, 500)
    try:
        candidates = list(
            db_sync.jobs.find(
                {"$text": {"$search": q}},
                {"score": {"$meta": "textScore"}},
            )
            .sort([("score", {"$meta": "textScore"})])
            .limit(fetch_limit)
        )
    except Exception as e:
        print(f"Error querying jobs (maybe text index missing?): {e}")
        return
        
    old_final_docs = rank_by_search_query(candidates, q)
    old_top_10 = [str(doc["_id"]) for doc in old_final_docs[:10]]
    
    # NEW LOGIC
    tokens = re.findall(r"[a-z0-9+#.]+", q.lower())
    if not tokens:
        docs = await db_async.jobs.find({"$text": {"$search": q}}).limit(limit).to_list(length=limit)
    else:
        min_matches = len(tokens) if len(tokens) <= 3 else len(tokens) - 1

        pipeline = [
            {"$match": {"$text": {"$search": q}}},
            {"$addFields": {
                "score": {"$meta": "textScore"},
                "title_hits": {
                    "$size": {
                        "$filter": {
                            "input": tokens,
                            "as": "token",
                            "cond": {"$regexMatch": {"input": {"$ifNull": ["$title", ""]}, "regex": "$$token", "options": "i"}}
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
                                    {"$regexMatch": {"input": {"$ifNull": ["$title", ""]}, "regex": "$$token", "options": "i"}},
                                    {"$regexMatch": {"input": {"$ifNull": ["$description", ""]}, "regex": "$$token", "options": "i"}}
                                ]
                            }
                        }
                    }
                }
            }},
            {"$match": {"total_hits": {"$gte": min_matches}}},
            {"$sort": {"title_hits": -1, "total_hits": -1, "score": -1, "_id": 1}},
            {"$limit": limit}
        ]

        docs = await db_async.jobs.aggregate(pipeline).to_list(length=limit)
        if not docs:
            docs = await db_async.jobs.find({"$text": {"$search": q}}, {"score": {"$meta": "textScore"}}).sort([("score", {"$meta": "textScore"})]).limit(limit).to_list(length=limit)
            
    new_top_10 = [str(doc["_id"]) for doc in docs[:10]]
    
    print(f"{'Rank':<5} | {'Old Logic ID':<25} | {'New Logic ID':<25}")
    print("-" * 60)
    for i in range(10):
        old_id = old_top_10[i] if i < len(old_top_10) else "N/A"
        new_id = new_top_10[i] if i < len(new_top_10) else "N/A"
        print(f"{i+1:<5} | {old_id:<25} | {new_id:<25}")

asyncio.run(run_comparison())

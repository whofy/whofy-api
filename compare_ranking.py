import asyncio
from db.mongo import get_db, get_async_db

async def run_comparison():
    db_sync = get_db()
    db_async = get_async_db()
    
    skill_list = ["python", "fastapi", "mongodb", "aws", "docker"]
    
    # Check if there are any jobs in the DB at all to avoid errors
    if db_sync.jobs.count_documents({}) == 0:
        print("No jobs in database to test with.")
        return

    # OLD LOGIC
    query = {"$text": {"$search": " ".join(skill_list)}}
    
    # Try to execute query, if text index missing, handle it
    try:
        candidates = list(
            db_sync.jobs.find(query, {"score": {"$meta": "textScore"}})
            .sort([("score", {"$meta": "textScore"})])
            .limit(150)
        )
    except Exception as e:
        print(f"Error querying jobs (maybe text index missing?): {e}")
        return
        
    scored = []
    for doc in candidates:
        haystack = f"{doc.get('title', '')} {doc.get('description', '')}".lower()
        matched = [s for s in skill_list if s.lower() in haystack]
        scored.append((doc, matched))
    
    scored.sort(key=lambda pair: pair[0].get("last_seen_at") or "", reverse=True)
    scored.sort(key=lambda pair: len(pair[1]), reverse=True)
    old_top_10 = [str(pair[0]["_id"]) for pair in scored[:10]]
    
    # NEW LOGIC
    pipeline = [
        {"$match": query},
        {"$addFields": {
            "matched_skills": {
                "$filter": {
                    "input": skill_list,
                    "as": "skill",
                    "cond": {
                        "$or": [
                            {"$regexMatch": {"input": {"$ifNull": ["$title", ""]}, "regex": "$$skill", "options": "i"}},
                            {"$regexMatch": {"input": {"$ifNull": ["$description", ""]}, "regex": "$$skill", "options": "i"}}
                        ]
                    }
                }
            }
        }},
        {"$addFields": {"match_count": {"$size": "$matched_skills"}}},
        {"$sort": {"match_count": -1, "last_seen_at": -1, "_id": 1}},
        {"$limit": 50}
    ]
    docs = await db_async.jobs.aggregate(pipeline).to_list(length=50)
    new_top_10 = [str(doc["_id"]) for doc in docs[:10]]
    
    print(f"{'Rank':<5} | {'Old Logic ID':<25} | {'New Logic ID':<25}")
    print("-" * 60)
    for i in range(10):
        old_id = old_top_10[i] if i < len(old_top_10) else "N/A"
        new_id = new_top_10[i] if i < len(new_top_10) else "N/A"
        print(f"{i+1:<5} | {old_id:<25} | {new_id:<25}")

asyncio.run(run_comparison())

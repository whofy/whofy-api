import asyncio
import re
from db.mongo import get_db, get_async_db

async def test_regex_bug():
    db = get_async_db()
    q = "c++ node.js"
    tokens = re.findall(r"[a-z0-9+#.]+", q.lower())
    
    # 1. BEFORE FIX
    try:
        pipeline_before = [
            {"$match": {"$text": {"$search": q}}},
            {"$addFields": {
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
            }}
        ]
        await db.jobs.aggregate(pipeline_before).to_list(length=1)
        print("BEFORE FIX: Success (Unexpected!)")
    except Exception as e:
        print(f"BEFORE FIX ERROR (Expected): {e}")

    # 2. AFTER FIX (using indexOfCP and toLower)
    try:
        pipeline_after = [
            {"$match": {"$text": {"$search": q}}},
            {"$addFields": {
                "total_hits": {
                    "$size": {
                        "$filter": {
                            "input": tokens,
                            "as": "token",
                            "cond": {
                                "$or": [
                                    {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$title", ""]}}, {"$toLower": "$$token"}]}, 0]},
                                    {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$description", ""]}}, {"$toLower": "$$token"}]}, 0]}
                                ]
                            }
                        }
                    }
                }
            }}
        ]
        docs = await db.jobs.aggregate(pipeline_after).to_list(length=1)
        print("AFTER FIX: Success!")
    except Exception as e:
        print(f"AFTER FIX ERROR: {e}")

asyncio.run(test_regex_bug())

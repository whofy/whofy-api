import asyncio
from db.mongo import get_async_db

async def test_search():
    db = get_async_db()
    
    # We will search for a query containing c++ and node.js
    q = "senior c++ node.js developer"
    
    # Simulating what jobs.py does now
    import re
    tokens = re.findall(r"[a-z0-9+#.]+", q.lower())
    
    pipeline = [
        {"$match": {"$text": {"$search": q}}},
        {"$addFields": {
            "title_hits": {
                "$size": {
                    "$filter": {
                        "input": tokens,
                        "as": "token",
                        "cond": {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$title", ""]}}, {"$toLower": "$$token"}]}, 0]}
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
                                {"$gte": [{"$indexOfCP": [{"$toLower": {"$ifNull": ["$description", ""]}}, {"$toLower": "$$token"}]}, 0]}
                            ]
                        }
                    }
                }
            }
        }},
        {"$match": {"total_hits": {"$gte": 1}}}, # just need any hits for testing
        {"$limit": 5}
    ]
    
    print(f"Testing query: {q}")
    print(f"Extracted tokens: {tokens}")
    try:
        docs = await db.jobs.aggregate(pipeline).to_list(length=5)
        print(f"SUCCESS! Query executed safely.")
        print(f"Found {len(docs)} documents.")
        if docs:
            print(f"Top doc ID: {docs[0]['_id']}")
            print(f"Title: {docs[0].get('title')}")
    except Exception as e:
        print(f"ERROR executing pipeline: {e}")

asyncio.run(test_search())

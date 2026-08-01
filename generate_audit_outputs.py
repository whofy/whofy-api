import os
import subprocess
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
from listings.shared.storage import DB_NAME

async def audit():
    print("=== ITEM 1: Sync calls in fetch_api/, chatbot/, parsing/ ===")
    cmd1 = 'findstr /S /R "requests\.[a-z]* pymongo MongoClient" fetch_api\*.py chatbot\*.py parsing\*.py'
    res1 = subprocess.run(cmd1, shell=True, capture_output=True, text=True)
    print(res1.stdout.strip() if res1.stdout else "No matches found.")

    print("\n=== ITEM 4: N+1 query patterns (for loops vs await db) ===")
    cmd4_1 = 'findstr /S /R "for.*in" fetch_api\*.py'
    cmd4_2 = 'findstr /S /R "await.*db\." fetch_api\*.py'
    res4_1 = subprocess.run(cmd4_1, shell=True, capture_output=True, text=True)
    res4_2 = subprocess.run(cmd4_2, shell=True, capture_output=True, text=True)
    print("Loops found:")
    for line in res4_1.stdout.strip().split('\n'):
        if 'for' in line and not 'serialize_job' in line and not 'split' in line and not '_SPAM_RE' in line and not 'db.jobs.distinct' in line:
            print("  " + line)
    print("DB calls found:")
    for line in res4_2.stdout.strip().split('\n'):
        print("  " + line)

    print("\n=== ITEM 6: Memory growth / Background tasks ===")
    cmd6 = 'findstr /S /R "lru_cache BackgroundTasks" fetch_api\*.py main.py'
    res6 = subprocess.run(cmd6, shell=True, capture_output=True, text=True)
    print(res6.stdout.strip() if res6.stdout else "No matches found.")

    print("\n=== ITEM 3: EXPLAIN() on queries ===")
    from config.settings import settings
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[DB_NAME]
    
    # 1. Matches query (no skills)
    base_filter = {"source": "greenhouse"}
    exp1 = await db.command({
        "explain": {
            "find": "jobs",
            "filter": base_filter,
            "sort": {"posted_at": -1, "_id": 1},
            "skip": 0,
            "limit": 50
        },
        "verbosity": "executionStats"
    })
    
    # 2. Search query (fallback to pure text)
    exp2 = await db.command({
        "explain": {
            "find": "jobs",
            "filter": {"$text": {"$search": "python"}},
            "sort": {"score": {"$meta": "textScore"}},
            "skip": 0,
            "limit": 200
        },
        "verbosity": "executionStats"
    })
    
    print("Winning plan for /api/matches (no skills):")
    print(exp1['queryPlanner']['winningPlan'])
    print("\nWinning plan for /api/search (pure text):")
    print(exp2['queryPlanner']['winningPlan'])

if __name__ == "__main__":
    asyncio.run(audit())

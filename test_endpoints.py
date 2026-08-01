import httpx
import asyncio

async def test_endpoints():
    async with httpx.AsyncClient() as client:
        # Test /api/matches
        print("Testing /api/matches with skills 'c++,node.js'")
        matches_res = await client.get("http://127.0.0.1:8000/api/matches?skills=c%2B%2B,node.js")
        print(f"Matches Status: {matches_res.status_code}")
        if matches_res.status_code == 200:
            data = matches_res.json()
            jobs = data.get("jobs", [])
            print(f"Found {len(jobs)} matches.")
            for i, job in enumerate(jobs[:3]):
                print(f"  {i+1}. {job['title']} (Matched: {job.get('matchedSkills')})")
        else:
            print(matches_res.text)
            
        print("\n" + "="*40 + "\n")
        
        # Test /api/search
        print("Testing /api/search with query 'senior c++ node.js developer'")
        search_res = await client.get("http://127.0.0.1:8000/api/search?q=senior+c%2B%2B+node.js+developer")
        print(f"Search Status: {search_res.status_code}")
        if search_res.status_code == 200:
            jobs = search_res.json()
            print(f"Found {len(jobs)} search results.")
            for i, job in enumerate(jobs[:3]):
                print(f"  {i+1}. {job['title']}")
        else:
            print(search_res.text)

if __name__ == "__main__":
    asyncio.run(test_endpoints())

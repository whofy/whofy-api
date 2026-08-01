import asyncio
import httpx
import time
from datetime import datetime

async def fetch_chat(session, message, idx):
    start = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Request {idx} started")
    try:
        response = await session.post(
            "http://127.0.0.1:8000/api/chat",
            json={"message": message, "history": []},
            timeout=30.0
        )
        end = time.time()
        print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Request {idx} finished with status {response.status_code} in {end-start:.2f}s")
        return response.json()
    except Exception as e:
        end = time.time()
        print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Request {idx} failed: {e} in {end-start:.2f}s")
        return None

async def main():
    async with httpx.AsyncClient() as session:
        # Fire 2 concurrent requests
        print("Firing 2 concurrent requests to /api/chat...")
        tasks = [
            fetch_chat(session, "How do I upload a resume?", 1),
            fetch_chat(session, "What companies are on Whofy?", 2)
        ]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())

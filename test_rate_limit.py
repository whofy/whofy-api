import requests
import time

def test_rate_limits():
    url = "http://localhost:8001/api/locations"
    print(f"Testing rate limit on {url} (Limit is 10/minute).")
    print("-" * 50)
    
    # We will send 12 requests.
    for i in range(1, 13):
        resp = requests.get(url)
        if resp.status_code == 200:
            print(f"Request {i:2d}: [SUCCESS] Status {resp.status_code}")
        elif resp.status_code == 429:
            print(f"Request {i:2d}: [BLOCKED] Status {resp.status_code} - Body: {resp.text}")
        else:
            print(f"Request {i:2d}: [ERROR] Status {resp.status_code} - Body: {resp.text}")
            
        time.sleep(0.1)

if __name__ == "__main__":
    test_rate_limits()

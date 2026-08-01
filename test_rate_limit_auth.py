
from fastapi.testclient import TestClient
from main import app
from unittest.mock import patch
from fastapi import HTTPException, Request
from fetch_api.auth import get_current_user

def mock_get_current_user(request: Request):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "")
    if token == "valid_1":
        return "user_1"
    elif token == "valid_2":
        return "user_2"
    else:
        raise HTTPException(status_code=401, detail="Invalid token")

# Override for the FastAPI route dependency
app.dependency_overrides[get_current_user] = mock_get_current_user

client = TestClient(app)

# Override for the limiter's direct import
@patch("fetch_api.auth.get_current_user", side_effect=mock_get_current_user)
def test_rate_limits(mock_func):
    url = "/api/saved-jobs"
    print(f"Testing rate limit on {url} (Limit is 30/minute).")
    print("-" * 50)
    
    print("--- Sending requests for user_1 (valid_1) ---")
    for i in range(1, 33):
        resp = client.get(url, headers={"Authorization": "Bearer valid_1"})
        if resp.status_code == 200:
            if i >= 28: # Print the last few success requests before limit
                print(f"User 1 Request {i:2d}: [SUCCESS] Status {resp.status_code}")
        elif resp.status_code == 429:
            print(f"User 1 Request {i:2d}: [BLOCKED] Status {resp.status_code} - Body: {resp.text}")
        else:
            print(f"User 1 Request {i:2d}: [ERROR] Status {resp.status_code} - Body: {resp.text}")

    print("\n--- Sending requests for user_2 (valid_2) ---")
    # user_2 should have a fresh bucket and succeed
    for i in range(1, 4):
        resp = client.get(url, headers={"Authorization": "Bearer valid_2"})
        if resp.status_code == 200:
            print(f"User 2 Request {i:2d}: [SUCCESS] Status {resp.status_code}")
        elif resp.status_code == 429:
            print(f"User 2 Request {i:2d}: [BLOCKED] Status {resp.status_code} - Body: {resp.text}")
        else:
            print(f"User 2 Request {i:2d}: [ERROR] Status {resp.status_code} - Body: {resp.text}")

    print("\n--- Sending request with invalid token ---")
    resp = client.get(url, headers={"Authorization": "Bearer invalid_token"})
    if resp.status_code == 401:
        print(f"Invalid Token Request: [REJECTED] Status 401 - Body: {resp.text}")
    else:
        print(f"Invalid Token Request: [ERROR] Status {resp.status_code} - Body: {resp.text}")

if __name__ == "__main__":
    test_rate_limits()

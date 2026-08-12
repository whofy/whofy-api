"""
Tests for POST /api/chat in chatbot/router.py.

Guards against regressions of the fixes applied on 2026-08-11 (F-09, N-09):
  - Fix A — 20/minute rate limit
  - Fix B — 3000-char message cap + 30-entry history cap
  - Fix C — singleton Groq client (indirectly — not a testable behavior at this layer)
"""


# ─────────────────────────────────────────────────────────────
# Input validation — caps enforced BEFORE any Groq call
# ─────────────────────────────────────────────────────────────

def test_chat_rejects_empty_message(client, auth_headers):
    """A whitespace-only message should return 400."""
    r = client.post("/api/chat", json={"message": "   ", "history": []}, headers=auth_headers)
    assert r.status_code == 400
    assert "empty" in r.json()["detail"].lower()


def test_chat_rejects_message_over_3000_chars(client, auth_headers):
    """Fix B regression guard — messages beyond MAX_MESSAGE_CHARS get 422 before hitting Groq."""
    oversize = "a" * 3001
    r = client.post("/api/chat", json={"message": oversize, "history": []}, headers=auth_headers)
    assert r.status_code == 422


def test_chat_rejects_history_over_30_entries(client, auth_headers):
    """Fix B regression guard — history beyond MAX_HISTORY_ENTRIES gets 422."""
    oversize_history = [{"from": "user", "text": "hi"}] * 31
    r = client.post(
        "/api/chat",
        json={"message": "hi", "history": oversize_history},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_chat_accepts_boundary_message_length(client, mock_groq_chat, auth_headers):
    """Exactly 3000 chars is at the boundary and must be accepted."""
    boundary_msg = "a" * 3000
    r = client.post("/api/chat", json={"message": boundary_msg, "history": []}, headers=auth_headers)
    assert r.status_code == 200
    assert "reply" in r.json()


def test_chat_accepts_boundary_history_length(client, mock_groq_chat, auth_headers):
    """Exactly 30 history entries is at the boundary and must be accepted."""
    history = [{"from": "user", "text": "hi"}] * 30
    r = client.post(
        "/api/chat",
        json={"message": "hello", "history": history},
        headers=auth_headers,
    )
    assert r.status_code == 200


# ─────────────────────────────────────────────────────────────
# Happy path — normal message returns a reply
# ─────────────────────────────────────────────────────────────

def test_chat_accepts_normal_message(client, mock_groq_chat, auth_headers):
    r = client.post(
        "/api/chat",
        json={"message": "How do I filter jobs by location?", "history": []},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"reply"}
    assert isinstance(body["reply"], str)
    assert len(body["reply"]) > 0


# ─────────────────────────────────────────────────────────────
# Rate limiting — 20/minute per user
# ─────────────────────────────────────────────────────────────

def test_chat_rate_limit_blocks_at_21st_request(rate_limited_client_fresh, auth_headers):
    """Fix A regression guard — 21st request within the same minute must be blocked."""
    body = {"message": "ping", "history": []}
    # First 20 requests should succeed
    for i in range(20):
        r = rate_limited_client_fresh.post("/api/chat", json=body, headers=auth_headers)
        assert r.status_code == 200, f"Request {i + 1}/20 unexpectedly failed with {r.status_code}"

    # 21st request should be rate-limited
    r = rate_limited_client_fresh.post("/api/chat", json=body, headers=auth_headers)
    assert r.status_code == 429

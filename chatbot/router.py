from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from chatbot.chat_service import get_chat_response
from fetch_api.limiter import limiter

router = APIRouter()

MAX_MESSAGE_CHARS = 3000
MAX_HISTORY_ENTRIES = 30


class ChatMessage(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    history: list[dict] = Field(default_factory=list, max_length=MAX_HISTORY_ENTRIES)


@router.post("/api/chat")
@limiter.limit("20/minute")
async def chat(body: ChatMessage, request: Request):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    reply = await get_chat_response(body.message, body.history)
    return {"reply": reply}

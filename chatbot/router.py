from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from chatbot.chat_service import get_chat_response

router = APIRouter()


class ChatMessage(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/api/chat")
async def chat(body: ChatMessage):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    reply = await get_chat_response(body.message, body.history)
    return {"reply": reply}

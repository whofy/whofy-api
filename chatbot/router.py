from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from chatbot.chat_service import get_chat_response

router = APIRouter()


class ChatMessage(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/api/chat")
def chat(body: ChatMessage):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    try:
        reply = get_chat_response(body.message, body.history)
        return {"reply": reply}
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

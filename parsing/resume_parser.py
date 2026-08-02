import asyncio
import io
import json
import os
import logging

logger = logging.getLogger(__name__)

import fitz  # PyMuPDF
from docx import Document
from groq import AsyncGroq, APIError, RateLimitError
from fastapi import HTTPException
from config.settings import settings

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
PARSE_MODEL = "openai/gpt-oss-120b"

RESUME_SCHEMA = {
    "type": "object",
    "properties": {
        "skills": {"type": "array", "items": {"type": "string"}},
        "location": {"type": "string"},
        "experienceLevel": {"type": "string"},
        "education": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "required": ["skills", "location", "experienceLevel", "education", "summary"],
}

PROMPT = """You are parsing a resume. Extract the following as JSON matching the schema:
- skills: a flat list of technical/professional skills mentioned (max 15, most relevant first)
- location: the candidate's city, or "" if not stated
- experienceLevel: one short phrase like "Fresher", "0-1 years", "2-3 years", or "" if unclear
- education: list of degree/institution strings, most recent first
- summary: a 1-2 sentence professional summary in third person

Resume text:
---
{text}
---
"""


class UnsupportedFileType(ValueError):
    pass


class EmptyResumeText(ValueError):
    pass


def extract_text(filename: str, content: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return _extract_pdf_text(content)
    if ext == ".docx":
        return _extract_docx_text(content)
    raise UnsupportedFileType(f"Unsupported file format: {ext}")


def _extract_pdf_text(content: bytes) -> str:
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def _extract_docx_text(content: bytes) -> str:
    doc = Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs)


async def structure_resume(text: str) -> dict:
    api_key = settings.groq_resume_parser_api_key
    if not api_key:
        print("[Resume Parser] ERROR: GROQ_RESUME_PARSER_API_KEY is not set in .env")
        raise HTTPException(status_code=500, detail="GROQ_RESUME_PARSER_API_KEY environment variable is not set")

    client = AsyncGroq(api_key=api_key)

    try:
        response = await client.chat.completions.create(
            model=PARSE_MODEL,
            messages=[
                {"role": "user", "content": PROMPT.format(text=text[:15000])}
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
    except RateLimitError as e:
        logger.error(f"[Resume Parser] ERROR: Groq API rate limit reached — {e}")
        raise HTTPException(status_code=429, detail="Resume parsing is temporarily unavailable — API rate limit reached. Please try again later.")
    except APIError as e:
        logger.error(f"[Resume Parser] ERROR: Groq API error — {e}")
        raise HTTPException(status_code=503, detail="Resume parsing failed due to an upstream service error. Please try again later.")

    return json.loads(response.choices[0].message.content)


async def parse_resume(filename: str, content: bytes) -> dict:
    text = await asyncio.to_thread(extract_text, filename, content)
    if not text or not text.strip():
        raise EmptyResumeText("Could not read any text from this file.")
    return await structure_resume(text)

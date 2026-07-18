import io
import json
import os

import fitz  # PyMuPDF
from docx import Document
from google import genai
from google.genai import types

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB, matches Dropzone.jsx's stated limit
PARSE_MODEL = "gemini-3.1-flash-lite"

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


def structure_resume(text: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=PARSE_MODEL,
        contents=PROMPT.format(text=text[:15000]),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RESUME_SCHEMA,
        ),
    )
    return json.loads(response.text)


def parse_resume(filename: str, content: bytes) -> dict:
    text = extract_text(filename, content)
    if not text or not text.strip():
        raise EmptyResumeText("Could not read any text from this file.")
    return structure_resume(text)

import logging
import os

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from fetch_api.limiter import limiter
from parsing.resume_parser import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    EmptyResumeText,
    NotAResume,
    UnsupportedFileType,
    parse_resume,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/upload-resume")
@limiter.limit("5/minute")
async def upload_resume(request: Request, file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload a PDF or DOCX resume.",
        )

    chunks, total = [], 0
    while chunk := await file.read(8192):
        total += len(chunk)
        if total > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="File too large. Max 5MB.")
        chunks.append(chunk)
    content = b"".join(chunks)

    if not content:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    try:
        resume = await parse_resume(file.filename, content)
    except UnsupportedFileType:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload a PDF or DOCX resume.",
        )
    except EmptyResumeText:
        raise HTTPException(
            status_code=422,
            detail="Could not read any text from this file. If it's a scanned image, try a text-based PDF or DOCX instead.",
        )
    except NotAResume:
        raise HTTPException(
            status_code=422,
            detail="This doesn't look like a resume. Please upload your resume or CV.",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Resume parsing failed")
        raise HTTPException(
            status_code=502,
            detail="Resume analysis failed. Please try again.",
        )

    return {"resume": resume}

import os

from fastapi import APIRouter, File, HTTPException, UploadFile

from parsing.resume_parser import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    EmptyResumeText,
    UnsupportedFileType,
    parse_resume,
)

router = APIRouter()


@router.post("/api/upload-resume")
async def upload_resume(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload a PDF or DOCX resume.",
        )

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Max 5MB.")

    try:
        resume = parse_resume(file.filename, content)
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

    return {"resume": resume}

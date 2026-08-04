from datetime import datetime
from typing import Optional, List, Any, Annotated, Literal
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict, BeforeValidator, PlainSerializer, field_validator
from bson import ObjectId

def validate_object_id(v: Any) -> ObjectId:
    if isinstance(v, ObjectId):
        return v
    if isinstance(v, str) and ObjectId.is_valid(v):
        return ObjectId(v)
    raise ValueError("Invalid ObjectId")

# Pydantic V2 compatible ObjectId annotation
PyObjectId = Annotated[
    ObjectId,
    BeforeValidator(validate_object_id),
    PlainSerializer(lambda x: str(x), return_type=str)
]

class DataQualityFlag(str, Enum):
    MISSING_POSTED_AT = "missing_posted_at"
    MISSING_DESCRIPTION = "missing_description"

class Job(BaseModel):
    """
    Canonical schema for a Job document in MongoDB.
    """
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    
    # Required core fields
    source: str = Field(min_length=1)
    source_job_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    location: str = Field(min_length=1)
    apply_url: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)
    
    # Date fields (stored as native BSON Date/ISODate in MongoDB, not strings)
    # Note: motor/pymongo will automatically serialize Python `datetime` objects to BSON Dates.
    posted_at: Optional[datetime] = None
    added_at: datetime
    last_seen_at: datetime
    
    # Flag to indicate missing or estimated data (e.g., "missing_posted_at", "missing_description")
    data_quality_flags: List[DataQualityFlag] = Field(default_factory=list)
    
    # Optional fields
    description: Optional[str] = None
    # We make company_domain strictly optional, as scrapers like LinkedIn/RemoteOK do not provide it.
    # It will be derived/guessed at serialization time for the frontend.
    company_domain: Optional[str] = None
    
    @field_validator("company_domain", "description", mode="before")
    @classmethod
    def normalize_optional_strings(cls, v):
        if v == "" or (isinstance(v, str) and not v.strip()):
            return None
        return v
    
    # Required fields derived during enrichment. Must be populated before saving.
    required_skills: List[str]
    work_type: Literal["Remote", "Hybrid", "On-site"]
    experience_level: str = Field(min_length=1)
    lang_checked: bool
    
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

class SavedJobSnapshot(BaseModel):
    title: str
    company: str
    location: str

class SavedJob(BaseModel):
    """
    Canonical schema for a Saved Job.
    """
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    user_id: str
    
    # Properly typed as an ObjectId reference, not a string
    job_id: PyObjectId
    
    # Native datetime
    saved_at: datetime
    
    # Snapshot is now strictly required
    snapshot: SavedJobSnapshot
    
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

class CompanyLogo(BaseModel):
    """
    Canonical schema for a Company Logo cache entry.
    """
    id: Optional[PyObjectId] = Field(alias="_id", default=None)
    company_key: str
    logo_url: Optional[str] = None
    
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )

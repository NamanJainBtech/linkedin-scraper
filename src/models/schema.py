from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class JoinedDate(BaseModel):
    raw_text: Optional[str] = None
    display_text: Optional[str] = None  # Retains verbatim approximate date text
    iso_date: Optional[str] = None


class ProfilePresence(BaseModel):
    has_photo: Optional[bool] = None
    has_custom_url: Optional[bool] = None


class AboutThisMember(BaseModel):
    joined_date: Optional[JoinedDate] = None
    profile_presence: Optional[ProfilePresence] = None
    verification_status: Optional[str] = None


class ContactInfo(BaseModel):
    emails: List[str] = Field(default_factory=list)
    phones: List[str] = Field(default_factory=list)
    websites: List[str] = Field(default_factory=list)
    connected_date: Optional[str] = None
    twitter: Optional[str] = None


class ExperienceItem(BaseModel):
    title: str
    company: Optional[str] = None
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    is_current: bool = False
    description: Optional[str] = None


class EducationItem(BaseModel):
    school: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None  # Raw date string from DOM (e.g. "2000 - 2004")
    start_year: Optional[int] = None
    end_year: Optional[int] = None


class CertificationItem(BaseModel):
    name: str
    issuer: Optional[str] = None
    issue_date: Optional[str] = None


class ProfileData(BaseModel):
    public_identifier: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    headline: Optional[str] = None
    location: Optional[str] = None
    summary: Optional[str] = None
    connections_count: Optional[int] = None
    followers_count: Optional[int] = None
    about_this_member: Optional[AboutThisMember] = None
    contact_info: Optional[ContactInfo] = None
    experience: List[ExperienceItem] = Field(default_factory=list)
    education: List[EducationItem] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    certifications: List[CertificationItem] = Field(default_factory=list)


class ExtractedProfileRecord(BaseModel):
    url: str
    extracted_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    extraction_mode: str  # "cookie" or "scale"
    extraction_status: str  # "success", "partial", "failed"
    errors: List[str] = Field(default_factory=list)  # Captured error/warning list matching JD section 4 schema
    error_message: Optional[str] = None
    profile: Optional[ProfileData] = None

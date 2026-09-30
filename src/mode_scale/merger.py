from typing import Dict, Any, Optional, List
from src.models.schema import (
    ExtractedProfileRecord,
    ProfileData,
    AboutThisMember,
    ContactInfo,
    ExperienceItem,
    EducationItem
)
from src.utils.validator import canonicalize_linkedin_url
from src.mode_cookie.extractor import extract_public_id
from src.utils.logger import setup_logger

logger = setup_logger("merger")


def parse_int_safe(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            return int(val)
        import re
        clean = re.sub(r"[^\d]", "", str(val))
        return int(clean) if clean else None
    except Exception:
        return None


def parse_bd_experience(bd_data: Dict[str, Any]) -> List[ExperienceItem]:
    experiences = []
    raw_exp = (
        bd_data.get("experience") or
        bd_data.get("experiences") or
        bd_data.get("positions") or
        bd_data.get("work_experience") or
        []
    )

    if isinstance(raw_exp, list):
        for item in raw_exp:
            if isinstance(item, dict):
                title = (
                    item.get("title") or
                    item.get("position") or
                    item.get("role") or
                    item.get("title_name") or
                    item.get("subtitle") or
                    "Position"
                )
                company = (
                    item.get("company") or
                    item.get("company_name") or
                    item.get("org_name") or
                    item.get("name") or
                    item.get("subtitle") or
                    "Company"
                )
                experiences.append(ExperienceItem(
                    title=str(title).strip(),
                    company=str(company).strip(),
                    location=item.get("location") or item.get("location_name"),
                    start_date=str(item.get("start_date") or item.get("start_year") or item.get("start") or ""),
                    end_date=str(item.get("end_date") or item.get("end_year") or item.get("end") or ""),
                    is_current=bool(item.get("is_current", False)),
                    description=item.get("description") or item.get("summary")
                ))
            elif isinstance(item, str) and item.strip():
                experiences.append(ExperienceItem(title=item.strip(), company="Unknown Company"))

    # Fallback: if no experience list, check current_company / current_company_name / position
    if not experiences:
        curr_company = bd_data.get("current_company_name") or bd_data.get("current_company")
        if isinstance(curr_company, dict):
            curr_company = curr_company.get("name") or curr_company.get("company_name") or str(curr_company)

        curr_title = bd_data.get("position") or bd_data.get("headline") or bd_data.get("title")
        if curr_company or curr_title:
            experiences.append(ExperienceItem(
                title=str(curr_title or "Position").strip(),
                company=str(curr_company or "Company").strip(),
                is_current=True
            ))

    return experiences


def parse_bd_education(bd_data: Dict[str, Any]) -> List[EducationItem]:
    educations = []
    raw_edu = (
        bd_data.get("education") or
        bd_data.get("educations_details") or
        bd_data.get("educations") or
        bd_data.get("schools") or
        []
    )

    if isinstance(raw_edu, list):
        for item in raw_edu:
            if isinstance(item, dict):
                school = (
                    item.get("school") or
                    item.get("institution") or
                    item.get("school_name") or
                    item.get("institution_name") or
                    item.get("title") or
                    item.get("name") or
                    item.get("subtitle") or
                    "Institution"
                )
                educations.append(EducationItem(
                    school=str(school).strip(),
                    degree=item.get("degree") or item.get("degree_name"),
                    field_of_study=item.get("field_of_study") or item.get("major") or item.get("subject"),
                    start_year=parse_int_safe(item.get("start_year") or item.get("start_date")),
                    end_year=parse_int_safe(item.get("end_year") or item.get("end_date"))
                ))
            elif isinstance(item, str) and item.strip():
                educations.append(EducationItem(school=item.strip()))
    elif isinstance(raw_edu, str) and raw_edu.strip():
        educations.append(EducationItem(school=raw_edu.strip()))
    return educations


def parse_bd_skills(bd_data: Dict[str, Any]) -> List[str]:
    skills = []
    raw_skills = bd_data.get("skills") or bd_data.get("skill_names") or bd_data.get("skills_list") or []
    
    if isinstance(raw_skills, list):
        for s in raw_skills:
            if isinstance(s, dict):
                name = s.get("name") or s.get("title") or s.get("skill")
                if name:
                    skills.append(str(name).strip())
            elif isinstance(s, str) and s.strip():
                skills.append(s.strip())
    return skills


def merge_brightdata_and_modals(
    url: str,
    bd_data: Optional[Dict[str, Any]],
    about_modal: Optional[AboutThisMember],
    contact_modal: Optional[ContactInfo]
) -> ExtractedProfileRecord:
    canonical_url = canonicalize_linkedin_url(url)
    captured_errors: List[str] = []
    
    if not bd_data and not about_modal and not contact_modal:
        msg = "No data retrieved from Bright Data API or Playwright modal extractor."
        return ExtractedProfileRecord(
            url=canonical_url,
            extraction_mode="scale",
            extraction_status="failed",
            errors=[msg],
            error_message=msg
        )

    bd_data = bd_data or {}
    contact_modal = contact_modal or ContactInfo()

    if not bd_data:
        captured_errors.append("Bright Data API payload missing or empty")
    if not about_modal:
        captured_errors.append("Section 2B About This Member modal data missing")

    full_name = bd_data.get("name") or bd_data.get("full_name") or f"{bd_data.get('first_name', '')} {bd_data.get('last_name', '')}".strip() or None
    first_name = bd_data.get("first_name") or (full_name.split()[0] if full_name else None)
    last_name = bd_data.get("last_name") or (" ".join(full_name.split()[1:]) if full_name and len(full_name.split()) > 1 else None)

    headline = bd_data.get("position") or bd_data.get("headline") or bd_data.get("title") or bd_data.get("occupation")
    location = bd_data.get("location") or bd_data.get("city") or bd_data.get("country")
    summary = bd_data.get("about") or bd_data.get("summary") or bd_data.get("bio") or bd_data.get("description")

    connections_count = parse_int_safe(bd_data.get("connections") or bd_data.get("connections_count") or bd_data.get("num_connections"))
    followers_count = parse_int_safe(bd_data.get("followers") or bd_data.get("followers_count") or bd_data.get("num_followers"))

    experiences = parse_bd_experience(bd_data)
    educations = parse_bd_education(bd_data)
    skills = parse_bd_skills(bd_data)

    bd_email = bd_data.get("email") or bd_data.get("personal_email")
    if bd_email and str(bd_email).strip() not in contact_modal.emails:
        contact_modal.emails.append(str(bd_email).strip())

    bd_website = bd_data.get("website") or bd_data.get("personal_website")
    if bd_website and str(bd_website).strip() not in contact_modal.websites:
        contact_modal.websites.append(str(bd_website).strip())

    profile = ProfileData(
        public_identifier=extract_public_id(canonical_url),
        first_name=first_name,
        last_name=last_name,
        full_name=full_name,
        headline=headline,
        location=location,
        summary=summary,
        connections_count=connections_count,
        followers_count=followers_count,
        about_this_member=about_modal,
        contact_info=contact_modal,
        experience=experiences,
        education=educations,
        skills=skills
    )

    status = "success" if (full_name and about_modal) else ("partial" if full_name else "failed")

    return ExtractedProfileRecord(
        url=canonical_url,
        extraction_mode="scale",
        extraction_status=status,
        errors=captured_errors,
        error_message="; ".join(captured_errors) if captured_errors else None,
        profile=profile
    )

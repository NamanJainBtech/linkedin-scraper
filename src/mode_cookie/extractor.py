import os
import re
from typing import Optional, List, Tuple
from playwright.async_api import Page
from bs4 import BeautifulSoup, Tag

from src.models.schema import (
    ExtractedProfileRecord,
    ProfileData,
    ExperienceItem,
    EducationItem,
    CertificationItem,
)
from src.shared.modal_about import extract_about_this_member
from src.shared.modal_contact import extract_contact_info
from src.utils.logger import setup_logger

logger = setup_logger("mode_cookie")

# Noise lines to strip from all sections
_NOISE_LINES = {
    "Experience", "Education", "Skills", "Certifications",
    "Show all", "Endorsed by", "Notifications", "Messaging",
    "Feed", "Search", "LinkedIn", "Activity", "Follow", "More",
    "Message", "Connect", "Contact info", "Full-time", "Part-time",
    "Self-employed", "Freelance", "Contract", "Internship", "Seasonal",
    "Languages", "Volunteer experience", "Publications", "Patents",
    "Honors & awards", "Test scores", "Courses", "Projects",
}

# Employment type tokens
_EMPLOYMENT_TYPES = {
    "Full-time", "Part-time", "Self-employed", "Freelance",
    "Contract", "Internship", "Seasonal",
}


class SecurityCheckpointException(Exception):
    """Raised when LinkedIn triggers an authwall, login wall, checkpoint, or CAPTCHA."""
    pass


def extract_public_id(url: str) -> Optional[str]:
    match = re.search(r"/in/([^/?#]+)", url)
    return match.group(1) if match else None


def parse_number(text: str) -> Optional[int]:
    """Parse integers from strings like '500+', '1,234', '646'."""
    text = str(text).replace("+", "").replace(",", "").strip()
    try:
        return int(re.sub(r"[^\d]", "", text)) if text else None
    except ValueError:
        return None


def clean_lines(raw_text: str, extra_noise: Optional[set] = None) -> List[str]:
    """Split text by newlines, strip whitespace, remove known noise words."""
    noise = _NOISE_LINES | (extra_noise or set())
    lines = []
    for line in raw_text.split("\n"):
        line = line.strip()
        if line and line not in noise and len(line) > 1:
            lines.append(line)
    return lines


def _find_sdui_section(soup: BeautifulSoup, key_suffix: str) -> Optional[Tag]:
    """Find a LinkedIn SDUI profile card section by its trailing key."""
    return soup.find(id=lambda i: i and i.endswith(key_suffix))


def _find_sdui_section_contains(soup: BeautifulSoup, keyword: str) -> Optional[Tag]:
    """Find SDUI section whose ID contains a given keyword."""
    return soup.find(id=lambda i: i and keyword in i)


def _is_date_line(line: str) -> bool:
    """Return True if this line looks like a date range."""
    return bool(re.search(r"\d{4}", line) and (
        " – " in line or " - " in line or "Present" in line
    ))


def _is_duration_line(line: str) -> bool:
    """Return True if this line looks like a tenure duration (e.g. '14 yrs 10 mos')."""
    return bool(re.search(r"\d+\s*(yr|mo)", line, re.I))


def _split_date_range(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Split a raw LinkedIn date-range string into (start_date, end_date).

    Examples:
      "May 2022 - Present · 4 yrs 5 mos"  →  ("May 2022", None)
      "Aug 2021 - Apr 2022 · 9 mos"        →  ("Aug 2021", "Apr 2022")
      "2002 – 2005"                         →  ("2002", "2005")
    """
    if not raw:
        return None, None

    # Strip the duration suffix (everything after " · ")
    date_part = re.split(r"\s*[·•]\s*", raw)[0].strip()

    # Try splitting on " – " (em-dash) or " - " (hyphen with spaces)
    for sep in (" – ", " - ", "–", "-"):
        if sep in date_part:
            parts = date_part.split(sep, 1)
            start = parts[0].strip() or None
            end_raw = parts[1].strip() if len(parts) > 1 else None
            end = None if not end_raw or end_raw.lower() == "present" else end_raw
            return start, end

    return date_part or None, None


def parse_topcard(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[int]]:
    """
    Returns (full_name, headline, location, connections_count) from the SDUI Topcard section.

    LinkedIn SDUI topcard layout (clean_lines output):
      [0] Full Name
      [1] Headline
      [2] "Company · School" mini-block (always contains '·', skip)
      [3] Location (city/region — no '·', no digit prefix)
      [4+] Company/School logos repeated, then "500+"/"N", then "connections"
    """
    topcard = _find_sdui_section(soup, "Topcard")
    if not topcard:
        for h2 in soup.find_all("h2"):
            txt = h2.get_text(strip=True)
            if txt and txt not in _NOISE_LINES and len(txt) > 2:
                return txt, None, None, None
        return None, None, None, None

    lines = clean_lines(topcard.get_text(separator="\n"))

    full_name = lines[0] if lines else None
    headline = lines[1] if len(lines) > 1 else None
    location = None
    connections_count = None

    if len(lines) > 3:
        candidate = lines[3]
        if (
            "·" not in candidate
            and candidate not in _NOISE_LINES
            and not re.search(r"^\d", candidate)
            and not _is_date_line(candidate)
            and not _is_duration_line(candidate)
        ):
            location = candidate

    for i, line in enumerate(lines):
        if line.lower() == "connections" and i > 0:
            connections_count = parse_number(lines[i - 1])
            break

    if not connections_count:
        raw = topcard.get_text(separator=" ")
        m = re.search(r"([\d,]+\+?)\s*connections", raw, re.I)
        if m:
            connections_count = parse_number(m.group(1))

    return full_name, headline, location, connections_count


# ── Section map: maps h2 text (lowercase) to section type ──────────────────
_H2_SECTION_MAP = {
    "education": "education",
    "skills": "skills",
    "languages": "languages",
    "certifications": "certifications",
    "licenses & certifications": "certifications",
    "about": "about",
    "experience": "experience",
    "courses": "courses",
    "projects": "projects",
    "honors & awards": "awards",
    "volunteer experience": "volunteer",
    "publications": "publications",
    "patents": "patents",
}


def _parse_education_years(date_range: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """Extract (start_year, end_year) integers from a date range string like '2005 – 2007'."""
    if not date_range:
        return None, None
    years = [int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", date_range)]
    start_year = years[0] if len(years) >= 1 else None
    end_year = years[1] if len(years) >= 2 else None
    return start_year, end_year


def _parse_education_start_date(date_range: Optional[str], start_year: Optional[int]) -> Optional[str]:
    """Extract start_date string (e.g. '2005' or 'Sep 2005') from a date range string."""
    if not date_range:
        return str(start_year) if start_year else None
    for sep in (" – ", " - ", "–", "-"):
        if sep in date_range:
            parts = date_range.split(sep, 1)
            start_part = parts[0].strip()
            if start_part:
                return start_part
    return str(start_year) if start_year else date_range.strip()


def _is_valid_skill_name(txt: str) -> bool:
    """Return True if txt is a genuine skill name and not metadata/endorsement noise."""
    if not txt or txt in _NOISE_LINES:
        return False
    txt_clean = txt.strip()
    txt_lower = txt_clean.lower()
    if txt_lower.startswith("skills") or txt_lower.startswith("endorsed by"):
        return False
    if re.search(r"^\d+\s*endorsement", txt_lower):
        return False
    if re.search(r"^show all \d+", txt_lower):
        return False
    if re.search(r"\d+\s+colleagues?", txt_lower):
        return False
    if len(txt_clean) > 80:
        return False
    return True


def _scan_all_sections(soup: BeautifulSoup) -> dict:
    """
    Scan the entire page for all profile sections, keyed by section type.

    Strategy:
    1. Scan h2/h3 tags across the entire DOM for known section headers.
    2. Scan containers with IDs matching profileCard / sdui.profile.card patterns.
    3. Check full-page SDUI trailing key IDs.

    Returns a dict: {"education": Tag, "skills": Tag, "experience": Tag, ...}
    """
    sections: dict = {}

    # 1. Scan headers (h2, h3) across the DOM
    for header_tag in ("h2", "h3"):
        for header in soup.find_all(header_tag):
            txt = header.get_text(strip=True).lower()
            txt_clean = re.sub(r"\s+", " ", txt).strip()

            section_type = None
            for key, stype in _H2_SECTION_MAP.items():
                if key in txt_clean:
                    section_type = stype
                    break

            if section_type and section_type not in sections:
                container = header.find_parent(["section", "div"])
                parent = header.parent
                while parent and parent.name not in ("body", "html"):
                    p_id = parent.get("id", "")
                    if p_id and ("card" in p_id.lower() or "section" in p_id.lower() or "profile" in p_id.lower()):
                        container = parent
                        break
                    if parent.name == "section":
                        container = parent
                        break
                    parent = parent.parent

                if container:
                    sections[section_type] = container
                    logger.debug(f"Found section '{section_type}' via header '{txt_clean}'")

    # 2. Collect candidate section containers by ID
    candidates = soup.find_all(
        id=lambda i: i and (
            "profileCard" in i or
            "sdui.profile.card" in i or
            "profilesCards" in i or
            "profile-cards" in i
        )
    )

    for container in candidates:
        h2 = container.find("h2")
        if not h2:
            continue
        h2_text = h2.get_text(strip=True).lower()
        section_type = _H2_SECTION_MAP.get(h2_text)
        if section_type and section_type not in sections:
            sections[section_type] = container
            logger.debug(f"Found section '{section_type}' (id={container.get('id','')[:60]})")

    # 3. Also check full-page SDUI sections by trailing key
    for suffix, stype in [
        ("ExperienceTopLevelSection", "experience"),
        ("EducationTopLevelSection", "education"),
        ("SkillsTopLevelSection", "skills"),
        ("CertificationsTopLevelSection", "certifications"),
        ("LanguagesTopLevelSection", "languages"),
    ]:
        tag = _find_sdui_section(soup, suffix)
        if tag and stype not in sections:
            sections[stype] = tag

    return sections


def _parse_standalone_role(chunks: List[str], company_override: Optional[str] = None) -> Optional[ExperienceItem]:
    """
    Parse a single role entry from its ordered text chunks.

    Chunk patterns:
      Pattern A: [title, subtitle?, "Company · type", date · duration, location?]
      Pattern B: [title, company_name, date · duration, location?]
    """
    if not chunks:
        return None

    title = chunks[0]
    if title in _NOISE_LINES or len(title) < 2:
        return None

    company = company_override
    raw_date = None
    is_current = False
    location = None

    for k in range(1, len(chunks)):
        chunk = chunks[k]
        if _is_date_line(chunk):
            raw_date = chunk
            is_current = "Present" in chunk
            if k + 1 < len(chunks):
                loc = chunks[k + 1]
                if (
                    not _is_date_line(loc)
                    and not _is_duration_line(loc)
                    and loc not in _NOISE_LINES
                    and loc not in _EMPLOYMENT_TYPES
                ):
                    location = loc
            break
        elif _is_duration_line(chunk):
            continue
        elif chunk in _EMPLOYMENT_TYPES:
            continue
        elif "·" in chunk and not _is_date_line(chunk):
            parts = [p.strip() for p in chunk.split("·")]
            company = parts[0]
        elif not company:
            company = chunk

    start_date, end_date = _split_date_range(raw_date)

    return ExperienceItem(
        title=title,
        company=company,
        start_date=start_date,
        end_date=end_date,
        is_current=is_current,
        location=location,
    )


def parse_dom_experience(soup: BeautifulSoup, sections: Optional[dict] = None) -> List[ExperienceItem]:
    """Parse experience using DOM block detection on the ExperienceTopLevelSection."""
    experiences: List[ExperienceItem] = []

    exp_sec = (sections or {}).get("experience") if sections else None
    if not exp_sec:
        exp_sec = _find_sdui_section(soup, "ExperienceTopLevelSection")
    if not exp_sec:
        exp_sec = _find_sdui_section_contains(soup, "ExperienceOnly")
    if not exp_sec:
        return experiences

    ul = exp_sec.find("ul")
    if ul:
        ul_parent = ul.parent
        entry_container = ul_parent.parent
    else:
        inner_section = exp_sec.find("section")
        if inner_section:
            inner_div = inner_section.find("div")
            entry_container = inner_div if inner_div else inner_section
        else:
            entry_container = exp_sec

    if not entry_container:
        return experiences

    blocks = [k for k in entry_container.children if hasattr(k, "find") and k.get_text(strip=True)]

    for block in blocks:
        has_ul = bool(block.find("ul"))

        if has_ul:
            block_chunks = [c.strip() for c in block.get_text(separator="|").split("|") if c.strip()]
            company_name = block_chunks[0] if block_chunks else None
            if company_name in _NOISE_LINES:
                company_name = None

            for li in block.find_all("li"):
                li_chunks = [c.strip() for c in li.get_text(separator="|").split("|") if c.strip()]
                item = _parse_standalone_role(li_chunks, company_override=company_name)
                if item:
                    experiences.append(item)
        else:
            chunks = [c.strip() for c in block.get_text(separator="|").split("|") if c.strip()]
            item = _parse_standalone_role(chunks)
            if item:
                experiences.append(item)

    return experiences


def parse_dom_education(soup: BeautifulSoup, sections: Optional[dict] = None) -> List[EducationItem]:
    """Parse education items from the Education section."""
    educations: List[EducationItem] = []

    edu_sec = (sections or {}).get("education") if sections else None
    if not edu_sec:
        edu_sec = _find_sdui_section(soup, "EducationTopLevelSection")
    if not edu_sec:
        edu_sec = _find_sdui_section_contains(soup, "EducationOnly")
    if not edu_sec:
        return educations

    items = edu_sec.find_all("li", recursive=True)

    # No list items — try block-level entries
    if not items:
        ul = edu_sec.find("ul")
        container = ul.parent if ul else edu_sec
        blocks = [k for k in container.children if hasattr(k, "find") and k.get_text(strip=True)]
        for block in blocks:
            chunks = [c.strip() for c in block.get_text(separator="|").split("|") if c.strip()]
            chunks = [c for c in chunks if c not in _NOISE_LINES]
            if not chunks:
                continue
            school = chunks[0]
            degree = None
            date_range = None
            for c in chunks[1:]:
                if re.search(r"\d{4}", c) and not date_range:
                    date_range = c
                elif not degree and not re.search(r"\d{4}", c) and c not in _EMPLOYMENT_TYPES:
                    degree = c
            if school and school not in _NOISE_LINES:
                s_yr, e_yr = _parse_education_years(date_range)
                s_date = _parse_education_start_date(date_range, s_yr)
                educations.append(EducationItem(
                    school=school,
                    degree=degree,
                    start_date=s_date,
                    start_year=s_yr,
                    end_year=e_yr,
                ))
        return educations

    for item in items:
        chunks = [c.strip() for c in item.get_text(separator="|").split("|") if c.strip()]
        chunks = [c for c in chunks if c not in _NOISE_LINES]
        if not chunks:
            continue
        school = chunks[0]
        degree = None
        date_range = None
        for c in chunks[1:]:
            if re.search(r"\d{4}", c) and not date_range:
                date_range = c
            elif not degree and not re.search(r"\d{4}", c) and c not in _EMPLOYMENT_TYPES:
                degree = c
        if school and school not in _NOISE_LINES:
            s_yr, e_yr = _parse_education_years(date_range)
            s_date = _parse_education_start_date(date_range, s_yr)
            educations.append(EducationItem(
                school=school,
                degree=degree,
                start_date=s_date,
                start_year=s_yr,
                end_year=e_yr,
            ))

    return educations


def parse_dom_skills(soup: BeautifulSoup, sections: Optional[dict] = None) -> List[str]:
    """Parse top skills from the Skills section."""
    skills: List[str] = []

    skills_sec = (sections or {}).get("skills") if sections else None
    if not skills_sec:
        skills_sec = _find_sdui_section(soup, "SkillsTopLevelSection")
    if not skills_sec:
        skills_sec = _find_sdui_section_contains(soup, "SkillsOnly")
    if not skills_sec:
        skills_sec = soup.find(id=lambda i: i and "skill" in i.lower())
    if not skills_sec:
        skills_sec = soup.find(lambda t: t.get and t.get("aria-label") and "skill" in t.get("aria-label").lower())
    if not skills_sec:
        for h in soup.find_all(["h2", "h3"]):
            if "skill" in h.get_text(strip=True).lower():
                skills_sec = h.find_parent(["section", "div"])
                break
    if not skills_sec:
        return skills

    items = skills_sec.find_all("li", recursive=True)
    if items:
        for item in items:
            chunks = [c.strip() for c in item.get_text(separator="|").split("|") if c.strip()]
            if chunks:
                candidate = chunks[0]
                if _is_valid_skill_name(candidate) and candidate not in skills:
                    skills.append(candidate)
    else:
        lines = clean_lines(skills_sec.get_text(separator="\n"), extra_noise={"Skills"})
        for line in lines:
            if _is_valid_skill_name(line) and line not in skills:
                skills.append(line)

    return skills[:20]


def parse_dom_languages(soup: BeautifulSoup, sections: Optional[dict] = None) -> List[str]:
    """Parse languages from the Languages section."""
    languages: List[str] = []

    lang_sec = (sections or {}).get("languages") if sections else None
    if not lang_sec:
        lang_sec = _find_sdui_section_contains(soup, "Languages")
    if not lang_sec:
        lang_sec = soup.find(id=lambda i: i and "language" in i.lower())
    if not lang_sec:
        for h in soup.find_all(["h2", "h3", "span"]):
            txt = h.get_text(strip=True).lower()
            if txt == "languages" or txt.startswith("languages"):
                lang_sec = h.find_parent(["section", "div"])
                break
    if not lang_sec:
        return languages

    items = lang_sec.find_all("li", recursive=True)
    if items:
        for item in items:
            chunks = [c.strip() for c in item.get_text(separator="|").split("|") if c.strip()]
            txt = chunks[0] if chunks else None
            if txt and txt not in _NOISE_LINES and len(txt) < 50 and txt not in languages:
                languages.append(txt)
    else:
        lines = clean_lines(lang_sec.get_text(separator="\n"), extra_noise={"Languages"})
        for line in lines:
            if len(line) < 40 and line not in languages:
                languages.append(line)

    return languages[:10]


def parse_dom_certifications(soup: BeautifulSoup, sections: Optional[dict] = None) -> List[CertificationItem]:
    """Parse certifications/licenses from the Certifications section."""
    certs: List[CertificationItem] = []

    cert_sec = (sections or {}).get("certifications") if sections else None
    if not cert_sec:
        cert_sec = _find_sdui_section(soup, "CertificationsTopLevelSection")
    if not cert_sec:
        cert_sec = _find_sdui_section_contains(soup, "Certification")
    if not cert_sec:
        cert_sec = _find_sdui_section_contains(soup, "LicensesAndCertifications")
    if not cert_sec:
        cert_sec = soup.find(id=lambda i: i and ("certif" in i.lower() or "license" in i.lower()))
    if not cert_sec:
        for h in soup.find_all(["h2", "h3", "span"]):
            txt = h.get_text(strip=True).lower()
            if "certification" in txt or "license" in txt:
                cert_sec = h.find_parent(["section", "div"])
                break
    if not cert_sec:
        return certs

    items = cert_sec.find_all("li", recursive=True)
    if not items:
        return certs

    for item in items:
        chunks = [c.strip() for c in item.get_text(separator="|").split("|") if c.strip()]
        chunks = [c for c in chunks if c not in _NOISE_LINES]
        if not chunks:
            continue
        name = chunks[0]
        issuer = chunks[1] if len(chunks) > 1 else None
        if name and name not in _NOISE_LINES:
            certs.append(CertificationItem(name=name, issuer=issuer))

    return certs


def parse_summary(soup: BeautifulSoup, sections: Optional[dict] = None) -> Optional[str]:
    """Parse the About/summary section from SDUI."""
    about_sec = (sections or {}).get("about") if sections else None
    if not about_sec:
        about_sec = _find_sdui_section(soup, "About")
    if not about_sec:
        about_sec = _find_sdui_section_contains(soup, "AboutSection")
    if not about_sec:
        return None

    text = about_sec.get_text(separator="\n", strip=True)
    text = re.sub(r"^\s*About\s*\n?", "", text).strip()
    return text if text else None


async def extract_cookie_mode_profile(page: Page, url: str, save_debug_html: bool = False) -> ExtractedProfileRecord:
    """
    Mode A: Full Playwright extraction using LinkedIn session cookies.
    Uses the new LinkedIn SDUI DOM structure (2024+).

    Args:
        save_debug_html: If True, saves raw page HTML to output/<id>_debug.html for offline analysis.
    """
    captured_errors: List[str] = []
    try:
        logger.info(f"Navigating to {url} (Mode A - Cookie)...")
        await page.goto(url, wait_until="commit", timeout=30000)

        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        # Security Checkpoint Detection
        current_url = page.url.lower()
        if any(k in current_url for k in ("authwall", "login", "checkpoint", "challenge", "signup")):
            msg = f"SECURITY ALERT: Redirected to checkpoint/authwall ({page.url}). Aborting to protect account."
            logger.error(msg)
            raise SecurityCheckpointException(msg)

        # Wait for SDUI Topcard to confirm profile loaded
        try:
            await page.wait_for_selector("[id*='Topcard'], h2, main", timeout=12000)
        except Exception as e:
            captured_errors.append(f"Timeout waiting for profile elements: {e}")

        # ── Scroll strategy ──────────────────────────────────────────────────
        # Phase 1: Scroll to page bottom to trigger all lazy-loaded sections
        # (Education, Skills, Certifications sit below Experience)
        for _ in range(12):
            await page.mouse.wheel(0, 900)
            await page.wait_for_timeout(350)

        # Pause to let intersection observers hydrate all below-fold content
        await page.wait_for_timeout(1500)

        # Phase 2: Try to scroll the BelowActivity sections into view via JS
        await page.evaluate("""() => {
            const els = document.querySelectorAll('[id*="profileCardsBelowActivity"]');
            els.forEach(el => el.scrollIntoView({behavior: 'instant', block: 'center'}));
        }""")
        await page.wait_for_timeout(800)

        # Phase 3: Scroll back to top for clean HTML capture
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(500)
        # ──────────────────────────────────────────────────────────────────────

        html = await page.content()
        soup = BeautifulSoup(html, "lxml")

        # Optionally dump HTML for offline analysis (no extra cookie needed later)
        if save_debug_html:
            public_id = extract_public_id(url) or "unknown"
            debug_path = os.path.join("output", f"{public_id}_debug.html")
            os.makedirs("output", exist_ok=True)
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info(f"Saved debug HTML → {debug_path}")

        # Build a unified section map from the full DOM (covers all SDUI ID patterns)
        sections = _scan_all_sections(soup)
        logger.info(f"Detected sections: {list(sections.keys())}")

        # ── Section 2A: Top Card ────────────────────────────────────────────
        full_name, headline, location, connections_count = parse_topcard(soup)

        if not full_name:
            captured_errors.append("Profile full_name element not found in DOM")
            logger.warning(f"Could not extract full_name for {url}")

        first_name = full_name.split()[0] if full_name else None
        last_name = " ".join(full_name.split()[1:]) if full_name and len(full_name.split()) > 1 else None

        followers_count = None
        fol_match = re.search(r"([\d,]+)\s+followers", html, re.I)
        if fol_match:
            followers_count = parse_number(fol_match.group(1))

        # ── Summary / About ─────────────────────────────────────────────────
        summary = parse_summary(soup, sections)

        # ── Experience ──────────────────────────────────────────────────────
        experiences = parse_dom_experience(soup, sections)
        if not experiences:
            captured_errors.append("Experience section empty or not found in DOM")
            logger.warning(f"Experience not extracted for {url}")

        # ── Education ───────────────────────────────────────────────────────
        educations = parse_dom_education(soup, sections)

        # ── Skills ──────────────────────────────────────────────────────────
        skills = parse_dom_skills(soup, sections)

        # ── Languages ───────────────────────────────────────────────────────
        languages = parse_dom_languages(soup, sections)

        # ── Certifications ──────────────────────────────────────────────────
        certifications = parse_dom_certifications(soup, sections)

        # ── Section 2B: About This Member modal ─────────────────────────────
        about_this_member = await extract_about_this_member(page)
        if not about_this_member:
            captured_errors.append("Section 2B About This Member modal not triggered or missing")

        # ── Section 2C: Contact Info modal ──────────────────────────────────
        contact_info = await extract_contact_info(page)

        profile = ProfileData(
            public_identifier=extract_public_id(url),
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            headline=headline,
            location=location,
            summary=summary,
            connections_count=connections_count,
            followers_count=followers_count,
            about_this_member=about_this_member,
            contact_info=contact_info,
            experience=experiences,
            education=educations,
            skills=skills,
            languages=languages,
            certifications=certifications,
        )

        status = "success" if (full_name or experiences or educations) else "failed"

        return ExtractedProfileRecord(
            url=url,
            extraction_mode="cookie",
            extraction_status=status,
            errors=captured_errors,
            error_message="; ".join(captured_errors) if captured_errors else None,
            profile=profile,
        )

    except SecurityCheckpointException:
        raise

    except Exception as e:
        logger.error(f"Error extracting profile {url}: {e}", exc_info=True)
        captured_errors.append(str(e))
        return ExtractedProfileRecord(
            url=url,
            extraction_mode="cookie",
            extraction_status="failed",
            errors=captured_errors,
            error_message=str(e),
            profile=None,
        )

import re
from typing import Optional
from playwright.async_api import Page
from bs4 import BeautifulSoup
from src.models.schema import AboutThisMember, JoinedDate, ProfilePresence
from src.utils.logger import setup_logger

logger = setup_logger("modal_about")


async def extract_about_this_member(page: Page) -> Optional[AboutThisMember]:
    try:
        # Check if already on modal or try clicking trigger button
        about_button = page.locator("button:has-text('About this profile'), button:has-text('About this member'), a:has-text('About this profile')").first
        
        if await about_button.count() > 0 and await about_button.is_visible():
            await about_button.click()
            await page.wait_for_timeout(1000)

        # Grab modal element safely using .first
        modal = page.locator(".artdeco-modal[role='dialog'], div[role='dialog']:has-text('About this profile'), div[role='dialog']:has-text('Joined')").first
        
        if await modal.count() == 0:
            logger.debug("About this member modal not triggered or visible.")
            return None

        content_html = await modal.inner_html()
        soup = BeautifulSoup(content_html, "lxml")
        text_content = soup.get_text(separator=" ", strip=True)

        # Extract Joined Date with re.DOTALL and explicit boundaries
        joined_date = None
        joined_match = re.search(r"Joined\s+([A-Za-z]+\s+\d{4}|[^\.]+)", text_content, re.IGNORECASE | re.DOTALL)
        if joined_match:
            raw_text = joined_match.group(0).strip()
            # Retain verbatim display_text as required by specs
            display_text = raw_text
            
            # Simple ISO conversion if full Month Year is present
            iso_val = None
            month_year = re.search(r"Joined\s+([A-Za-z]+)\s+(\d{4})", raw_text, re.IGNORECASE)
            if month_year:
                months = {
                    "january": "01", "february": "02", "march": "03", "april": "04",
                    "may": "05", "june": "06", "july": "07", "august": "08",
                    "september": "09", "october": "10", "november": "11", "december": "12",
                    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06",
                    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"
                }
                m_str = month_year.group(1).lower()
                y_str = month_year.group(2)
                if m_str in months:
                    iso_val = f"{y_str}-{months[m_str]}-01"

            joined_date = JoinedDate(
                raw_text=raw_text,
                display_text=display_text,
                iso_date=iso_val
            )

        # Profile Presence
        has_photo = True
        if "no profile photo" in text_content.lower() or "default profile photo" in text_content.lower():
            has_photo = False

        presence = ProfilePresence(
            has_photo=has_photo,
            has_custom_url=True
        )

        # Verification status check (distinguish 'unverified' vs 'verified')
        lower_text = text_content.lower()
        if "unverified" in lower_text:
            verification = "Unverified"
        elif "verified" in lower_text or "identity verified" in lower_text:
            verification = "Verified"
        else:
            verification = "Unknown"

        # Dismiss modal safely
        close_btn = modal.locator("button[aria-label='Dismiss'], button[aria-label='Close']").first
        if await close_btn.count() > 0:
            await close_btn.click()

        return AboutThisMember(
            joined_date=joined_date,
            profile_presence=presence,
            verification_status=verification
        )

    except Exception as e:
        logger.warning(f"Error extracting Section 2B modal: {e}")
        return None

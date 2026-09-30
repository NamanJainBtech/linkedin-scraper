import re
from typing import Optional
from playwright.async_api import Page
from bs4 import BeautifulSoup
from src.models.schema import ContactInfo
from src.utils.logger import setup_logger

logger = setup_logger("modal_contact")


async def extract_contact_info(page: Page) -> ContactInfo:
    contact_info = ContactInfo()
    try:
        contact_link = page.locator("a#top-card-text-details-contact-info, a:has-text('Contact info')").first
        
        if await contact_link.count() > 0 and await contact_link.is_visible():
            await contact_link.click()
            await page.wait_for_timeout(1000)

        modal = page.locator(".artdeco-modal[role='dialog']:has-text('Contact Info'), div[role='dialog']:has-text('Contact')").first
        
        if await modal.count() == 0:
            logger.debug("Contact info modal not triggered or visible.")
            return contact_info

        content_html = await modal.inner_html()
        soup = BeautifulSoup(content_html, "lxml")

        # Extract Emails
        email_links = soup.select("a[href^='mailto:']")
        for link in email_links:
            email = link.get("href", "").replace("mailto:", "").strip()
            if email and email not in contact_info.emails:
                contact_info.emails.append(email)

        if not contact_info.emails:
            text = soup.get_text()
            found_emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text)
            for e in found_emails:
                if e not in contact_info.emails:
                    contact_info.emails.append(e)

        # Extract Websites
        website_links = soup.select("section.pv-contact-info__contact-type.ci-websites a, a[href*='http']")
        for w in website_links:
            href = w.get("href", "")
            if href and "linkedin.com" not in href and href not in contact_info.websites:
                contact_info.websites.append(href)

        # Extract Twitter
        twitter_elem = soup.find(text=re.compile(r"Twitter", re.I))
        if twitter_elem:
            parent = twitter_elem.find_parent("section") or twitter_elem.find_parent("div")
            if parent:
                contact_info.twitter = parent.get_text(strip=True).replace("Twitter", "").strip()

        # Extract Connected Date
        connected_elem = soup.find(text=re.compile(r"Connected", re.I))
        if connected_elem:
            parent = connected_elem.find_parent("section") or connected_elem.find_parent("div")
            if parent:
                contact_info.connected_date = parent.get_text(strip=True).replace("Connected", "").strip()

        # Dismiss modal safely
        close_btn = modal.locator("button[aria-label='Dismiss'], button[aria-label='Close']").first
        if await close_btn.count() > 0:
            await close_btn.click()

        return contact_info

    except Exception as e:
        logger.warning(f"Error extracting Section 2C modal: {e}")
        return contact_info

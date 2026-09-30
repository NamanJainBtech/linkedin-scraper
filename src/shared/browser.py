import json
import os
from typing import Optional, List, Dict
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright
from src.utils.logger import setup_logger

logger = setup_logger("browser")


def normalize_same_site(val: Optional[str]) -> str:
    if not val:
        return "Lax"
    v = str(val).lower()
    if "none" in v or "no_restriction" in v:
        return "None"
    elif "strict" in v:
        return "Strict"
    return "Lax"


def load_cookie_list(cookie_file_path: str) -> List[Dict]:
    if not os.path.exists(cookie_file_path):
        logger.warning(f"Cookie file not found at {cookie_file_path}. Proceeding without session cookies.")
        return []

    with open(cookie_file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        cookies = []
        for name, value in data.items():
            cookies.append({
                "name": name,
                "value": str(value),
                "domain": ".linkedin.com",
                "path": "/"
            })
        return cookies
    return []


class BrowserManager:
    def __init__(self, cookie_file: Optional[str] = None, headless: bool = True):
        self.cookie_file = cookie_file
        self.headless = headless
        self.playwright: Optional[Playwright] = None
        self.browser = None
        self.context: Optional[BrowserContext] = None

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ]
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

        # Mask navigator.webdriver
        await self.context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        if self.cookie_file:
            cookies = load_cookie_list(self.cookie_file)
            if cookies:
                clean_cookies = []
                for c in cookies:
                    raw_domain = str(c.get("domain", ".linkedin.com"))
                    domain = ".linkedin.com" if "linkedin.com" in raw_domain else raw_domain

                    cookie_dict = {
                        "name": c.get("name"),
                        "value": str(c.get("value", "")),
                        "domain": domain,
                        "path": c.get("path", "/"),
                        "sameSite": normalize_same_site(c.get("sameSite")),
                    }
                    if "secure" in c:
                        cookie_dict["secure"] = bool(c["secure"])
                    if "httpOnly" in c:
                        cookie_dict["httpOnly"] = bool(c["httpOnly"])
                    clean_cookies.append(cookie_dict)
                
                await self.context.add_cookies(clean_cookies)
                logger.info(f"Loaded {len(clean_cookies)} cookies into browser context with domain: .linkedin.com")

        return self

    async def new_page(self) -> Page:
        return await self.context.new_page()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.debug(f"Error during browser cleanup: {e}")

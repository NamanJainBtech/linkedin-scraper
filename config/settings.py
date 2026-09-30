import os
from dotenv import load_dotenv

load_dotenv()

BRIGHTDATA_API_KEY = os.getenv("BRIGHTDATA_API_KEY", "")
BRIGHTDATA_DATASET_ID = os.getenv("BRIGHTDATA_DATASET_ID", "gd_l1viktl72bvl7bjuj0")

DEFAULT_INPUT_FILE = "data/sample_urls.txt"
DEFAULT_OUTPUT_FILE = "output/extracted_profiles.json"
DEFAULT_COOKIE_FILE = "cookies/linkedin_cookies.json"

PAGE_TIMEOUT_MS = 30000
MODAL_TIMEOUT_MS = 5000

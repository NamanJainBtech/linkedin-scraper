import os
import re
from typing import List
from src.utils.logger import setup_logger

logger = setup_logger("validator")


def canonicalize_linkedin_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    # Extract public identifier from URL
    match = re.search(r"/in/([^/?#]+)", url)
    if match:
        pub_id = match.group(1).lower().rstrip("/")
        return f"https://www.linkedin.com/in/{pub_id}"
    
    # Fallback cleanup
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url.split("?")[0].rstrip("/").lower()


def load_urls(input_filepath: str, offset: int = 0, limit: int = None) -> List[str]:
    if not os.path.exists(input_filepath):
        raise FileNotFoundError(f"Input file not found at: {input_filepath}")

    raw_urls = []
    with open(input_filepath, "r", encoding="utf-8") as f:
        for line in f:
            clean = canonicalize_linkedin_url(line)
            if clean:
                raw_urls.append(clean)

    # Deduplicate while preserving original order
    seen = set()
    deduped = []
    for u in raw_urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)

    logger.info(f"Loaded {len(deduped)} unique canonical URLs from {input_filepath} (Raw count: {len(raw_urls)})")

    # Apply offset and limit after deduplication
    sliced = deduped[offset:]
    if limit is not None and limit > 0:
        sliced = sliced[:limit]

    logger.info(f"Sliced URL list to {len(sliced)} targets (Offset: {offset}, Limit: {limit})")
    return sliced

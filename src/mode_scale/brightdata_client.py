import asyncio
from typing import List, Dict, Any, Optional
import httpx
from config import settings
from src.utils.logger import setup_logger

logger = setup_logger("brightdata_client")


class BrightDataClient:
    def __init__(self, api_key: str = settings.BRIGHTDATA_API_KEY, dataset_id: str = settings.BRIGHTDATA_DATASET_ID):
        self.api_key = api_key
        self.dataset_id = dataset_id
        self.base_url = "https://api.brightdata.com"

    async def trigger_dataset_scrape(self, urls: List[str]) -> Optional[str]:
        if not self.api_key:
            logger.error("BRIGHTDATA_API_KEY is not set in environment or settings.")
            return None

        endpoint = f"{self.base_url}/datasets/v3/trigger"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        params = {
            "dataset_id": self.dataset_id,
            "include_errors": "true"
        }
        payload = [{"url": u} for u in urls]

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(endpoint, headers=headers, params=params, json=payload)
                if response.status_code != 200:
                    logger.error(f"Failed to trigger Bright Data dataset scrape (HTTP {response.status_code}): {response.text}")
                    return None
                
                data = response.json()
                snapshot_id = data.get("snapshot_id")
                logger.info(f"Bright Data job triggered successfully. Snapshot ID: {snapshot_id}")
                return snapshot_id
            except Exception as e:
                logger.error(f"Failed to trigger Bright Data dataset scrape: {e}")
                return None

    async def poll_snapshot_results(self, snapshot_id: str, poll_interval: int = 10, max_wait: int = 300) -> List[Dict[str, Any]]:
        endpoint = f"{self.base_url}/datasets/v3/snapshot/{snapshot_id}"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        elapsed = 0
        async with httpx.AsyncClient(timeout=30.0) as client:
            while elapsed < max_wait:
                try:
                    response = await client.get(endpoint, headers=headers, params={"format": "json"})
                    if response.status_code == 200:
                        results = response.json()
                        logger.info(f"Bright Data snapshot {snapshot_id} ready. Retrieved {len(results)} records.")
                        return results if isinstance(results, list) else [results]
                    elif response.status_code == 202:
                        logger.info(f"Snapshot {snapshot_id} still processing... waiting {poll_interval}s")
                        await asyncio.sleep(poll_interval)
                        elapsed += poll_interval
                    else:
                        logger.warning(f"Unexpected status code {response.status_code} from Bright Data snapshot API: {response.text}")
                        await asyncio.sleep(poll_interval)
                        elapsed += poll_interval
                except Exception as e:
                    logger.error(f"Error polling Bright Data snapshot: {e}")
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval

        logger.error(f"Timed out polling Bright Data snapshot {snapshot_id} after {max_wait}s")
        return []

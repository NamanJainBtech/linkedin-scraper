import time
from typing import Dict, Any


class ExtractionMetrics:
    def __init__(self, total_urls: int = 0):
        self.total_urls: int = total_urls
        self.processed_urls: int = 0
        self.successes: int = 0
        self.partials: int = 0
        self.failures: int = 0
        self.start_time: float = time.time()
        self.end_time: float = 0.0

    def record_result(self, status: str):
        self.processed_urls += 1
        if status == "success":
            self.successes += 1
        elif status == "partial":
            self.partials += 1
        else:
            self.failures += 1

    def finish(self):
        self.end_time = time.time()

    def get_summary(self) -> Dict[str, Any]:
        elapsed = (self.end_time or time.time()) - self.start_time
        avg_time = elapsed / self.processed_urls if self.processed_urls > 0 else 0.0
        return {
            "total_urls": self.total_urls,
            "processed_urls": self.processed_urls,
            "successes": self.successes,
            "partials": self.partials,
            "failures": self.failures,
            "elapsed_seconds": round(elapsed, 2),
            "avg_seconds_per_profile": round(avg_time, 2)
        }

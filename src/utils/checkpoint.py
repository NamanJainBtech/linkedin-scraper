import json
import os
from typing import Dict, List, Set, Any
from src.utils.validator import canonicalize_linkedin_url
from src.utils.logger import setup_logger

logger = setup_logger("checkpoint")


class CheckpointManager:
    def __init__(self, jsonl_filepath: str):
        self.jsonl_filepath = jsonl_filepath
        os.makedirs(os.path.dirname(self.jsonl_filepath) or ".", exist_ok=True)

    def load_processed_urls(self) -> Set[str]:
        processed: Set[str] = set()
        if not os.path.exists(self.jsonl_filepath):
            return processed

        try:
            with open(self.jsonl_filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        record = json.loads(line)
                        raw_url = record.get("url")
                        if raw_url:
                            processed.add(canonicalize_linkedin_url(raw_url))
        except Exception as e:
            logger.warning(f"Error reading existing checkpoint file {self.jsonl_filepath}: {e}")

        logger.info(f"Loaded {len(processed)} existing processed URLs from checkpoint {self.jsonl_filepath}")
        return processed

    def append_record(self, record_dict: Dict[str, Any]):
        try:
            with open(self.jsonl_filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record_dict, ensure_ascii=False) + "\n")
                f.flush()
        except Exception as e:
            logger.error(f"Failed to write record to checkpoint JSONL: {e}")

    def export_to_json(self, json_filepath: str) -> List[Dict[str, Any]]:
        records = []
        if not os.path.exists(self.jsonl_filepath):
            return records

        with open(self.jsonl_filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        os.makedirs(os.path.dirname(json_filepath) or ".", exist_ok=True)
        with open(json_filepath, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

        logger.info(f"Compiled {len(records)} checkpoint records into JSON output: {json_filepath}")
        return records

import asyncio
import os
import random
import sys
import click

from config import settings
from src.models.schema import ExtractedProfileRecord
from src.utils.validator import load_urls, canonicalize_linkedin_url
from src.utils.metrics import ExtractionMetrics
from src.utils.logger import setup_logger
from src.utils.checkpoint import CheckpointManager
from src.shared.browser import BrowserManager, load_cookie_list
from src.shared.modal_about import extract_about_this_member
from src.shared.modal_contact import extract_contact_info
from src.mode_cookie.extractor import extract_cookie_mode_profile, SecurityCheckpointException
from src.mode_scale.brightdata_client import BrightDataClient
from src.mode_scale.merger import merge_brightdata_and_modals

logger = setup_logger("main")


async def run_pipeline(
    input_file: str,
    output_file: str,
    cookie_file: str,
    scale_mode: bool,
    offset: int,
    limit: int,
    min_delay: float,
    max_delay: float,
    debug_html: bool = False,
):
    # Load and slice URLs
    urls = load_urls(input_file, offset=offset, limit=limit)
    if not urls:
        logger.error("No valid URLs found to process.")
        return

    jsonl_output_file = output_file.rsplit(".", 1)[0] + ".jsonl"
    checkpoint = CheckpointManager(jsonl_output_file)
    processed_urls = checkpoint.load_processed_urls()

    # Filter out already completed URLs for resume capability
    pending_urls = [u for u in urls if canonicalize_linkedin_url(u) not in processed_urls]
    logger.info(f"Pending execution count: {len(pending_urls)} (Already completed: {len(urls) - len(pending_urls)})")

    if not pending_urls:
        logger.info("All target URLs have already been processed in checkpoint file.")
        checkpoint.export_to_json(output_file)
        return

    metrics = ExtractionMetrics(total_urls=len(urls))
    has_cookies = bool(load_cookie_list(cookie_file))

    if scale_mode:
        logger.info("Running in Mode B (Scale Mode: Bright Data API)")
        bd_client = BrightDataClient()
        snapshot_id = await bd_client.trigger_dataset_scrape(pending_urls)
        
        bd_results_map = {}
        if snapshot_id:
            raw_bd_list = await bd_client.poll_snapshot_results(snapshot_id)
            for item in raw_bd_list:
                item_url = item.get("url") or item.get("input_url")
                if item_url:
                    bd_results_map[canonicalize_linkedin_url(item_url)] = item

        # If cookies are provided, run Playwright modal extractor for Section 2B & 2C
        if has_cookies:
            logger.info("Cookies detected: Extracting Section 2B & 2C browser modals via Playwright...")
            async with BrowserManager(cookie_file=cookie_file) as browser:
                for i, url in enumerate(pending_urls):
                    try:
                        if i > 0 and max_delay > 0:
                            delay = random.uniform(min_delay, max_delay)
                            await asyncio.sleep(delay)

                        page = await browser.new_page()
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(1500)

                        if "authwall" in page.url.lower() or "checkpoint" in page.url.lower():
                            raise SecurityCheckpointException(f"Redirected to checkpoint: {page.url}")

                        about_modal = await extract_about_this_member(page)
                        contact_modal = await extract_contact_info(page)
                        await page.close()

                        bd_data = bd_results_map.get(canonicalize_linkedin_url(url))
                        record = merge_brightdata_and_modals(url, bd_data, about_modal, contact_modal)

                        metrics.record_result(record.extraction_status)
                        checkpoint.append_record(record.model_dump())

                    except SecurityCheckpointException as sc_err:
                        logger.critical(f"ABORTING PIPELINE: Security Checkpoint triggered: {sc_err}")
                        print("\n[CRITICAL SECURITY ALERT] Aborting run to protect account from bans.")
                        sys.exit(1)

                    except Exception as e:
                        logger.error(f"Error processing {url} in Scale Mode: {e}")
                        failed_rec = ExtractedProfileRecord(
                            url=url,
                            extraction_mode="scale",
                            extraction_status="failed",
                            error_message=str(e)
                        )
                        metrics.record_result("failed")
                        checkpoint.append_record(failed_rec.model_dump())
        else:
            logger.warning("No cookies provided: Skipping Playwright browser visits. Generating records directly from Bright Data API payload...")
            for url in pending_urls:
                bd_data = bd_results_map.get(canonicalize_linkedin_url(url))
                record = merge_brightdata_and_modals(url, bd_data, None, None)
                metrics.record_result(record.extraction_status)
                checkpoint.append_record(record.model_dump())

    else:
        logger.info("Running in Mode A (Cookie Mode: Full Playwright Extraction)")
        if not has_cookies:
            logger.error("Mode A requires valid LinkedIn session cookies! Please create cookies/linkedin_cookies.json with your li_at cookie.")
            print("\n[ERROR] Cookie file missing or empty. Mode A requires a valid li_at cookie in cookies/linkedin_cookies.json.")
            sys.exit(1)

        async with BrowserManager(cookie_file=cookie_file) as browser:
            for i, url in enumerate(pending_urls):
                try:
                    if i > 0 and max_delay > 0:
                        delay = random.uniform(min_delay, max_delay)
                        await asyncio.sleep(delay)

                    page = await browser.new_page()
                    record = await extract_cookie_mode_profile(page, url, save_debug_html=debug_html)
                    await page.close()

                    metrics.record_result(record.extraction_status)
                    checkpoint.append_record(record.model_dump())

                except SecurityCheckpointException as sc_err:
                    logger.critical(f"ABORTING PIPELINE: Security Checkpoint triggered: {sc_err}")
                    print("\n[CRITICAL SECURITY ALERT] Aborting run immediately to protect account from bans.")
                    sys.exit(1)

                except Exception as e:
                    logger.error(f"Error processing {url} in Cookie Mode: {e}")
                    failed_rec = ExtractedProfileRecord(
                        url=url,
                        extraction_mode="cookie",
                        extraction_status="failed",
                        error_message=str(e)
                    )
                    metrics.record_result("failed")
                    checkpoint.append_record(failed_rec.model_dump())

    metrics.finish()

    # Compile JSONL checkpoint into final formatted JSON file
    checkpoint.export_to_json(output_file)

    # Print Performance Metrics Summary
    summary = metrics.get_summary()
    print("\n" + "="*50)
    print("       EXTRACTION PERFORMANCE METRICS SUMMARY       ")
    print("="*50)
    for k, v in summary.items():
        print(f"  {k:<25}: {v}")
    print("="*50 + "\n")


@click.command()
@click.option("--input", "-i", "input_file", default=settings.DEFAULT_INPUT_FILE, help="Path to LinkedIn URLs list file.")
@click.option("--output", "-o", "output_file", default=settings.DEFAULT_OUTPUT_FILE, help="Path to save extracted JSON output.")
@click.option("--cookies", "-c", "cookie_file", default=settings.DEFAULT_COOKIE_FILE, help="Path to linkedin_cookies.json file.")
@click.option("--scale", is_flag=True, default=False, help="Enable Mode B (Scale Mode: Bright Data + Playwright Modals).")
@click.option("--offset", default=0, type=int, help="Number of URLs to skip from top after deduplication.")
@click.option("--limit", default=None, type=int, help="Maximum number of URLs to process.")
@click.option("--min-delay", default=2.0, type=float, help="Minimum randomized delay between profile visits (seconds).")
@click.option("--max-delay", default=5.0, type=float, help="Maximum randomized delay between profile visits (seconds).")
@click.option("--debug-html", is_flag=True, default=False, help="Save raw page HTML to output/<id>_debug.html for offline DOM analysis.")
def main(input_file, output_file, cookie_file, scale, offset, limit, min_delay, max_delay, debug_html):
    """LinkedIn Profile Extractor CLI Pipeline"""
    asyncio.run(run_pipeline(
        input_file=input_file,
        output_file=output_file,
        cookie_file=cookie_file,
        scale_mode=scale,
        offset=offset,
        limit=limit,
        min_delay=min_delay,
        max_delay=max_delay,
        debug_html=debug_html,
    ))


if __name__ == "__main__":
    main()

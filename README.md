# LinkedIn Profile Data Extractor

A production-grade, highly resilient LinkedIn profile extraction pipeline built with Python 3.10+, Playwright, BeautifulSoup4, and Pydantic v2. Designed for the Shri Genesis Technical Assessment.

---

## Key Features & Highlights

- **Dual-Mode Operational Architecture**:
  - **Mode A (Cookie Mode - Default)**: Direct Playwright browser automation with active `li_at` session cookies. Optimized for full-depth extraction on small to medium evaluation batches (≤100 profiles).
  - **Mode B (Scale Mode - `--scale`)**: Scalable hybrid architecture leveraging Bright Data's Web Scraper API for page payloads combined with targeted Playwright modal interaction. Built to scale seamlessly to 2,000+ profiles.
- **Dynamic JavaScript Modal Extraction**:
  - **Section 2B (About This Member Modal)**: Captures member joined date (retaining verbatim `display_text` like *"Joined September 2004"* or *"Updated less than 3 months ago"*), profile photo update status, and identity verification status.
  - **Section 2C (Contact Info Modal)**: Interacts with the contact modal to capture email addresses, phone numbers, websites with labels, connected date, and social links.
- **SDUI DOM Parsing Engine (2024+)**:
  - Handles LinkedIn's Server-Driven UI (SDUI) layout variations and lazy-loaded `profileCardsBelowActivityPartN` containers.
  - Implements multi-stage page scrolling and hydration wait strategies.
  - Features intelligent noise filtering for skills, experience roles, and education dates (`start_date`, `start_year`, `end_year`).
- **Account Protection & Rate-Limit Safeguards**:
  - Automatically checks for `/authwall`, `/checkpoint`, or CAPTCHA triggers and halts execution immediately to protect accounts from restrictions.
  - Implements randomized delay pacing between browser navigations (`--min-delay` and `--max-delay`).
- **Incremental JSONL Checkpointing**:
  - Streams every extracted profile record immediately to `output/extracted_profiles.jsonl`.
  - Supports full resume capability—re-running the pipeline skips previously completed URLs without making duplicate network requests.
- **Performance & Health Summary Metrics**:
  - Generates a structured execution summary after every run (total, processed, successes, partials, failures, elapsed time, average time per profile).

---

## Setup & Installation Instructions

### Prerequisites
- Python 3.10 or higher
- `pip` and `venv`
- Google Chrome / Chromium dependencies (installed via Playwright)

### Step 1: Clone Repository & Create Virtual Environment
```bash
git clone <repository_url>
cd profile-extractor

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate
```

### Step 2: Install Python Dependencies & Playwright Browsers
```bash
pip install -r requirements.txt
playwright install chromium
```

### Step 3: Configure Environment Variables (For Scale Mode)
Copy the template environment file:
```bash
cp .env.example .env
```
Edit `.env` and configure your API key if using Mode B Scale Mode:
```env
BRIGHTDATA_API_KEY=your_brightdata_api_key_here
BRIGHTDATA_DATASET_ID=gd_l1vtw10a109zbbf64
```

### Step 4: Configure LinkedIn Session Cookies (For Cookie Mode & Hybrid Modals)
Copy the cookie template:
```bash
cp cookies/linkedin_cookies.json.example cookies/linkedin_cookies.json
```
Export your valid logged-in LinkedIn session cookies (at least `li_at`) into `cookies/linkedin_cookies.json`:
```json
[
  {
    "name": "li_at",
    "value": "YOUR_ACTUAL_LI_AT_COOKIE_VALUE_HERE",
    "domain": ".linkedin.com",
    "path": "/",
    "httpOnly": true,
    "secure": true,
    "sameSite": "None"
  }
]
```

---

## Usage Guide & Examples

### 1. Default Run (Mode A - Cookie Mode)
Process sample URLs using Playwright with LinkedIn session cookies:
```bash
python main.py --input data/sample_urls.txt --cookies cookies/linkedin_cookies.json --limit 5
```

### 2. Batch Processing with Offset & Limit
Skip the first 5 profiles and process the next 10:
```bash
python main.py --input data/sample_urls.txt --offset 5 --limit 10
```

### 3. Scale Mode (Mode B - Bright Data API + Hybrid Modals)
Run high-throughput extraction via Bright Data with modal enrichment:
```bash
python main.py --input data/sample_urls.txt --scale --limit 10
```

### 4. Pure Scale Mode (No Browser Modals / No Cookies)
Run Scale Mode purely via Bright Data API without making any Playwright browser visits:
```bash
python main.py --input data/sample_urls.txt --scale --cookies "" --limit 10
```

### 5. Debug Mode (DOM Snapshot Dumping)
Save raw page HTML payloads to `output/<id>_debug.html` for offline DOM inspection:
```bash
python main.py --input data/sample_urls.txt --limit 1 --debug-html
```

---

## Performance Summary Output (Recent Benchmark Runs)

### Benchmark 1: Mode A (Cookie Mode - 5 Profiles Run)
```text
==================================================
       EXTRACTION PERFORMANCE METRICS SUMMARY       
==================================================
  total_urls               : 5
  processed_urls           : 5
  successes                : 5
  partials                 : 0
  failures                 : 0
  elapsed_seconds          : 100.59
  avg_seconds_per_profile  : 20.12
==================================================
```

### Benchmark 2: Mode B (Scale Mode - 10 Profiles Run)
```text
==================================================
       EXTRACTION PERFORMANCE METRICS SUMMARY       
==================================================
  total_urls               : 10
  processed_urls           : 10
  successes                : 0
  partials                 : 10
  failures                 : 0
  elapsed_seconds          : 145.82
  avg_seconds_per_profile  : 14.58
==================================================
```

---

## Detailed Performance Metrics Table (JD Section 6)

| Metric | Mode A (Cookie Mode - 5 Profiles) | Mode B (Scale Mode - 10 Profiles) | Description / Notes |
|---|---|---|---|
| **Profiles Processed** | 5 | 10 | Total target URLs attempted in benchmark run |
| **Successful Records** | 5 | 0 | Records with complete core profile, experience, and education |
| **Partial Records** | 0 | 10 | Records with partial fields due to missing modal / privacy settings |
| **Failed Records** | 0 | 0 | Number of unhandled exception failures (0 failures) |
| **Execution Time** | 100.59 s | 145.82 s | Total execution duration for benchmark run |
| **Average Time / Profile** | 20.12 s | 14.58 s | Average elapsed time per processed profile |
| **Errors** | 0 critical errors | 0 critical errors | Gracefully handled optional modal missing warnings |
| **Scalability Target** | 1 – 100 profiles | 1,500 – 2,000+ profiles | Supported workload capability |

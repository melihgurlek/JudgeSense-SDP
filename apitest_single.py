import requests
import time
import pandas as pd
import os
import signal
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
from contextlib import contextmanager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constants
CSV_FILE = "legal_cases.csv"
BATCH_SIZE = 5  # Number of pages to process before saving
MAX_RETRIES = 5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
    "Content-Type": "application/json; charset=UTF-8",
    "Referer": "https://emsal.uyap.gov.tr/index",
    "X-Requested-With": "XMLHttpRequest"
}

# Global flag for graceful termination
terminate = False

# Set up signal handler for graceful termination


def signal_handler(sig, frame):
    global terminate
    logger.info("Received termination signal. Will exit after current batch...")
    terminate = True


# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)


@contextmanager
def create_session():
    """Create a robust session with retry logic and connection pooling"""
    session = requests.Session()

    # Configure retry strategy with exponential backoff
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=0.5,  # 0.5, 1, 2, 4... seconds between retries
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )

    # Apply retry strategy to both HTTP and HTTPS connections
    adapter = HTTPAdapter(max_retries=retry_strategy,
                          pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(HEADERS)

    try:
        yield session
    finally:
        session.close()


def get_last_page():
    """Determine the last successfully scraped page"""
    if os.path.exists(CSV_FILE):
        try:
            df = pd.read_csv(CSV_FILE)
            if not df.empty:
                return df["Page"].max()
            return 0
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            return 0
    return 0


def initialize_search(session):
    """Initialize the search query"""
    search_payload = {
        "data": {
            "aranan": "Hukuk",
            "arananKelime": "Hukuk"
        }
    }
    search_url = "https://emsal.uyap.gov.tr/arama"
    try:
        response = session.post(search_url, json=search_payload)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to initialize search: {e}")
        return False


def get_case_list(session, page):
    """Get the list of cases for a specific page with CAPTCHA handling"""
    case_list_payload = {
        "data": {
            "aranan": "Hukuk",
            "arananKelime": "Hukuk",
            "pageSize": 10,
            "pageNumber": page
        }
    }
    case_list_url = "https://emsal.uyap.gov.tr/aramalist"

    for attempt in range(MAX_RETRIES):
        try:
            response = session.post(case_list_url, json=case_list_payload)
            response.raise_for_status()
            case_data = response.json()

            # Check for CAPTCHA
            if case_data["metadata"]["FMC"] == "ADALET_RUNTIME_EXCEPTION":
                wait_time = 10 + (attempt * 5)  # Increasing wait time
                logger.warning(
                    f"CAPTCHA detected on page {page}! Waiting {wait_time} seconds...")
                time.sleep(wait_time)
                continue

            return case_data["data"]["data"]

        except Exception as e:
            wait_time = 5 + (attempt * 5)
            logger.error(
                f"Error fetching case list (attempt {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"Max retries reached for page {page}")
                return []

    return []


def get_explanation(session, case_id):
    """Get the explanation for a specific case with CAPTCHA handling"""
    explanation_url = f"https://emsal.uyap.gov.tr/getDokuman?id={case_id}"

    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(explanation_url)
            response.raise_for_status()
            explanation_json = response.json()

            # Check for CAPTCHA
            if explanation_json["metadata"]["FMC"] == "ADALET_RUNTIME_EXCEPTION":
                wait_time = 10 + (attempt * 5)
                logger.warning(
                    f"CAPTCHA detected for case {case_id}! Waiting {wait_time} seconds...")
                time.sleep(wait_time)
                continue

            raw_html = explanation_json.get("data", "")
            soup = BeautifulSoup(raw_html, "html.parser")
            return soup.get_text(separator="\n").strip()

        except Exception as e:
            wait_time = 5 + (attempt * 5)
            logger.error(
                f"Error fetching explanation for case {case_id} (attempt {attempt+1}/{MAX_RETRIES}): {e}")
            if attempt < MAX_RETRIES - 1:
                logger.info(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                logger.error(f"Max retries reached for case {case_id}")
                return "Error fetching explanation"

    return "Error fetching explanation"


def process_case_batch(session, cases_list):
    """Process a batch of cases using ThreadPoolExecutor"""
    case_data = []

    # Define a worker function that includes the session
    def fetch_explanation_worker(case):
        explanation = get_explanation(session, case["id"])
        return {
            "Page": case["page"],
            "Court Name": case["daire"],
            "Case Number": case["esasNo"],
            "Decision Number": case["kararNo"],
            "Decision Date": case["kararTarihi"],
            "Status": case["durum"],
            "Explanation": explanation
        }

    # Use ThreadPoolExecutor to fetch explanations in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_case = {executor.submit(
            fetch_explanation_worker, case): case for case in cases_list}
        for future in future_to_case:
            try:
                case_data.append(future.result())
            except Exception as e:
                logger.error(f"Error processing case: {e}")

    return case_data


def save_to_csv(data, mode="a"):
    """Save data to CSV file with proper handling"""
    try:
        df = pd.DataFrame(data)
        if df.empty:
            logger.warning("No data to save")
            return

        header = not os.path.exists(CSV_FILE) or mode == "w"
        df.to_csv(CSV_FILE, mode=mode, header=header,
                  index=False, encoding="utf-8")
        logger.info(f"Successfully saved {len(df)} cases to CSV")
    except Exception as e:
        logger.error(f"Error saving to CSV: {e}")
        # Save to backup file as emergency measure
        try:
            df.to_csv(f"backup_{int(time.time())}.csv",
                      index=False, encoding="utf-8")
            logger.info("Data saved to backup file")
        except Exception as backup_error:
            logger.critical(f"Failed to save backup: {backup_error}")


def main():
    last_page = get_last_page()
    start_page = last_page + 1
    logger.info(f"Starting scraper from page {start_page}")

    with create_session() as session:
        # Initialize search
        if not initialize_search(session):
            logger.error("Failed to initialize search. Exiting.")
            return

        current_page = start_page
        batch_data = []

        while not terminate:
            logger.info(f"Processing page {current_page}")

            # Get cases for current page
            cases_list = get_case_list(session, current_page)

            # Break if no more cases
            if not cases_list:
                logger.info("No more cases found. Scraping complete.")
                break

            # Add page number to each case for tracking
            for case in cases_list:
                case["page"] = current_page

            # Process cases and add to batch
            case_data = process_case_batch(session, cases_list)
            batch_data.extend(case_data)

            # Save data after batch is complete
            if len(batch_data) >= BATCH_SIZE * 10 or terminate:  # 10 cases per page * BATCH_SIZE
                logger.info(f"Saving batch of {len(batch_data)} cases...")
                save_to_csv(batch_data)
                batch_data = []  # Clear batch after saving

            current_page += 1

        # Save any remaining data
        if batch_data:
            logger.info(f"Saving final batch of {len(batch_data)} cases...")
            save_to_csv(batch_data)

    logger.info("Scraper finished successfully")


if __name__ == "__main__":
    main()

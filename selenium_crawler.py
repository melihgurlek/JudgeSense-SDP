from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import pandas as pd
import os
import signal
import logging
import sys

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
BATCH_SIZE = 2  # Number of pages to process before saving
MAX_RETRIES = 3
PAGE_WAIT_TIME = 3  # Seconds to wait for page loads

# Global flag for graceful termination
terminate = False

def signal_handler(sig, frame):
    global terminate
    logger.info("Received termination signal. Will exit after current batch...")
    terminate = True

signal.signal(signal.SIGINT, signal_handler)

def get_last_page():
    """Determine the last successfully scraped page from CSV"""
    if os.path.exists(CSV_FILE):
        try:
            df = pd.read_csv(CSV_FILE)
            if not df.empty and 'Page' in df.columns:
                return df["Page"].max()
            return 0
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            return 0
    return 0

def save_to_csv(data, mode="a"):
    """Save data to CSV with backup mechanism"""
    try:
        df = pd.DataFrame(data)
        if df.empty:
            logger.warning("No data to save")
            return

        header = not os.path.exists(CSV_FILE) or mode == "w"
        df.to_csv(CSV_FILE, mode=mode, header=header, index=False, encoding="utf-8")
        logger.info(f"Saved {len(df)} cases to CSV")
    except Exception as e:
        logger.error(f"Error saving to CSV: {e}")
        # Emergency backup
        try:
            backup_file = f"backup_{int(time.time())}.csv"
            df.to_csv(backup_file, index=False, encoding="utf-8")
            logger.info(f"Data saved to backup: {backup_file}")
        except Exception as backup_error:
            logger.critical(f"Backup failed: {backup_error}")

def process_page(driver, wait, current_page):
    """Process all cases on a single page"""
    cases = []
    try:
        rows = WebDriverWait(driver, 30).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "#detayAramaSonuclar tbody tr"))
        )
    except Exception as e:
        logger.error(f"Failed to find rows on page {current_page}: {e}")
        return []

    for row in rows:
        retries = 0
        while retries < MAX_RETRIES and not terminate:
            try:
                columns = row.find_elements(By.TAG_NAME, "td")
                if len(columns) < 5:
                    continue

                case_info = {
                    "Court Name": columns[0].text,
                    "Case Number": columns[1].text,
                    "Decision Number": columns[2].text,
                    "Decision Date": columns[3].text,
                    "Status": columns[4].text,
                    "Page": current_page
                }

                # Click to get explanation
                row.click()
                explanation = WebDriverWait(driver, 20).until(
                    EC.visibility_of_element_located((By.ID, "kararAlani"))
                ).text
                case_info["Explanation"] = explanation.strip()
                
                cases.append(case_info)
                break  # Success - exit retry loop

            except Exception as e:
                logger.warning(f"Retry {retries+1}/{MAX_RETRIES} for case: {e}")
                retries += 1
                time.sleep(2)
                if retries >= MAX_RETRIES:
                    logger.error(f"Failed to process case after {MAX_RETRIES} attempts")

    return cases

def main():
    # Initialize browser
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 20)

    last_page = get_last_page()
    current_page = last_page + 1
    logger.info(f"Resuming from page {current_page}")

    try:
        # Navigate to initial URL
        driver.get("https://emsal.uyap.gov.tr/#")
        
        # Perform initial search
        search_box = wait.until(EC.presence_of_element_located((By.TAG_NAME, "input")))
        search_box.send_keys("Hukuk" + Keys.RETURN)
        time.sleep(PAGE_WAIT_TIME)

        batch_data = []
        while not terminate:
            logger.info(f"Processing page {current_page}")
            
            # Process current page
            page_cases = process_page(driver, wait, current_page)
            batch_data.extend(page_cases)

            # Save batch
            if len(batch_data) >= BATCH_SIZE * 10:  # 10 cases per page * BATCH_SIZE
                logger.info(f"Saving batch of {len(batch_data)} cases")
                save_to_csv(batch_data)
                batch_data = []

            # Navigate to next page
            try:
                next_button = driver.find_element(By.ID, "detayAramaSonuclar_next")
                if "disabled" in next_button.get_attribute("class"):
                    logger.info("No more pages available")
                    break
                
                next_button.click()
                time.sleep(PAGE_WAIT_TIME)
                current_page += 1
            except Exception as e:
                logger.error(f"Failed to navigate to next page: {e}")
                break

    except Exception as e:
        logger.error(f"Critical error: {e}")
    finally:
        # Save remaining data
        if batch_data:
            logger.info(f"Saving final batch of {len(batch_data)} cases")
            save_to_csv(batch_data)
        
        driver.quit()
        logger.info("Scraper terminated gracefully")

if __name__ == "__main__":
    main()
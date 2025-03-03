from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
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
# Seconds to wait for user to solve CAPTCHA (3 minutes)
CAPTCHA_WAIT_TIME = 180

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
        df.to_csv(CSV_FILE, mode=mode, header=header,
                  index=False, encoding="utf-8")
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


def check_for_captcha(driver):
    """Check if the page has a CAPTCHA element"""
    try:
        # Add various CAPTCHA detection methods here
        # Check for common CAPTCHA elements
        captcha_elements = [
            "iframe[src*='recaptcha']",
            "iframe[src*='captcha']",
            ".g-recaptcha",
            "#recaptcha",
            ".captcha-container"
        ]

        for selector in captcha_elements:
            if len(driver.find_elements(By.CSS_SELECTOR, selector)) > 0:
                return True

        # Check for redirection to login/captcha page
        current_url = driver.current_url
        if "login" in current_url or "captcha" in current_url or "/uyap.gov.tr/" in current_url and "emsal" not in current_url:
            return True

        # Check if we're no longer on the expected results page
        if len(driver.find_elements(By.CSS_SELECTOR, "#detayAramaSonuclar")) == 0:
            # If we're not on the results page, we might be on a CAPTCHA or login page
            return True

        return False
    except Exception as e:
        logger.warning(f"Error checking for CAPTCHA: {e}")
        return False


def wait_for_captcha_solution(driver):
    """Wait for the user to solve the CAPTCHA and return to results page"""
    logger.info(
        f"CAPTCHA detected! Please solve the CAPTCHA manually. Waiting up to {CAPTCHA_WAIT_TIME} seconds...")

    # Maximize window to make CAPTCHA more visible
    driver.maximize_window()

    start_time = time.time()
    while time.time() - start_time < CAPTCHA_WAIT_TIME:
        try:
            # Check if we're back on the results page
            results_table = driver.find_elements(
                By.CSS_SELECTOR, "#detayAramaSonuclar")
            if len(results_table) > 0:
                logger.info(
                    "Results page detected. CAPTCHA appears to be solved!")
                return True

            # Wait a bit before checking again
            time.sleep(5)
        except Exception as e:
            logger.warning(f"Error while waiting for CAPTCHA solution: {e}")
            time.sleep(5)

    logger.error("CAPTCHA wait time exceeded. Terminating script.")
    return False


def process_page(driver, wait, current_page):
    """Process all cases on a single page"""
    global terminate  # Add this line to access the global terminate variable
    cases = []

    # First check if we need to handle CAPTCHA
    if check_for_captcha(driver):
        captcha_solved = wait_for_captcha_solution(driver)
        if not captcha_solved:
            return cases  # Return empty list if CAPTCHA not solved

    try:
        rows = WebDriverWait(driver, 30).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "#detayAramaSonuclar tbody tr"))
        )
    except TimeoutException:
        logger.error(f"Failed to find rows on page {current_page}")
        # Check again for CAPTCHA
        if check_for_captcha(driver):
            captcha_solved = wait_for_captcha_solution(driver)
            if not captcha_solved:
                return cases

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
                try:
                    explanation_element = WebDriverWait(driver, 20).until(
                        EC.visibility_of_element_located((By.ID, "kararAlani"))
                    )
                    explanation = explanation_element.text

                    # Check if explanation is empty or very short (likely an error)
                    if not explanation or len(explanation.strip()) < 10:
                        logger.warning(
                            "Empty or very short explanation detected. Possible CAPTCHA.")
                        if check_for_captcha(driver):
                            captcha_solved = wait_for_captcha_solution(driver)
                            if not captcha_solved:
                                return cases
                        retries += 1
                        continue

                    case_info["Explanation"] = explanation.strip()
                except TimeoutException:
                    # If we can't find the explanation area, check for CAPTCHA
                    logger.warning(
                        "No explanation area found. Checking for CAPTCHA...")
                    if check_for_captcha(driver):
                        captcha_solved = wait_for_captcha_solution(driver)
                        if not captcha_solved:
                            return cases
                    retries += 1
                    continue

                cases.append(case_info)
                break  # Success - exit retry loop

            except Exception as e:
                logger.warning(
                    f"Retry {retries+1}/{MAX_RETRIES} for case: {e}")
                retries += 1
                time.sleep(2)
                if retries >= MAX_RETRIES:
                    logger.error(
                        f"Failed to process case after {MAX_RETRIES} attempts")

    return cases


def reset_search_if_needed(driver, wait):
    """If we're redirected away from search results, try to get back"""
    global terminate  # Add this line to access the global terminate variable
    try:
        # Check if we're on the main page
        if "emsal.uyap.gov.tr" in driver.current_url and len(driver.find_elements(By.CSS_SELECTOR, "#detayAramaSonuclar")) == 0:
            logger.info(
                "No longer on search results page. Attempting to reset search...")

            # Check if we need to handle CAPTCHA first
            if check_for_captcha(driver):
                captcha_solved = wait_for_captcha_solution(driver)
                if not captcha_solved:
                    return False

            # Try to get back to search page
            driver.get("https://emsal.uyap.gov.tr/#")
            time.sleep(PAGE_WAIT_TIME)

            # Perform search again
            search_box = wait.until(
                EC.presence_of_element_located((By.TAG_NAME, "input")))
            search_box.send_keys("Hukuk" + Keys.RETURN)
            time.sleep(PAGE_WAIT_TIME)

            return True
    except Exception as e:
        logger.error(f"Error resetting search: {e}")
    return False


def main():
    global terminate  # Add this line to access the global terminate variable

    # Initialize browser with more undetectable options
    options = webdriver.ChromeOptions()
    # Comment the headless option to make it easier to solve CAPTCHAs manually
    # options.add_argument("--headless")

    # Add options that might help bypass CAPTCHA detection
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    # Set normal window size to appear more like a human user
    driver.set_window_size(1366, 768)

    # Execute CDP commands to modify navigator.webdriver property
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    wait = WebDriverWait(driver, 20)

    last_page = get_last_page()
    current_page = last_page + 1
    logger.info(f"Resuming from page {current_page}")

    try:
        # Navigate to initial URL
        driver.get("https://emsal.uyap.gov.tr/#")

        # Perform initial search
        search_box = wait.until(
            EC.presence_of_element_located((By.TAG_NAME, "input")))
        search_box.send_keys("Hukuk" + Keys.RETURN)
        time.sleep(PAGE_WAIT_TIME)

        batch_data = []
        consecutive_empty_pages = 0

        while not terminate:
            logger.info(f"Processing page {current_page}")

            # Process current page
            page_cases = process_page(driver, wait, current_page)

            # Check if we got any cases
            if not page_cases:
                consecutive_empty_pages += 1
                logger.warning(
                    f"No cases found on page {current_page}. Empty page count: {consecutive_empty_pages}")

                # If we've had multiple empty pages, try to reset the search
                if consecutive_empty_pages >= 2:
                    logger.warning(
                        "Multiple empty pages detected. Attempting to reset search...")
                    search_reset = reset_search_if_needed(driver, wait)

                    if search_reset:
                        # If search was reset, we need to navigate to the correct page
                        logger.info(
                            f"Search reset. Navigating to page {current_page}...")
                        for i in range(1, current_page):
                            next_button = driver.find_element(
                                By.ID, "detayAramaSonuclar_next")
                            if "disabled" in next_button.get_attribute("class"):
                                logger.info("No more pages available")
                                terminate = True
                                break
                            next_button.click()
                            time.sleep(PAGE_WAIT_TIME)

                        consecutive_empty_pages = 0
                        continue
                    else:
                        logger.error("Failed to reset search. Terminating.")
                        terminate = True
            else:
                consecutive_empty_pages = 0  # Reset counter when we successfully get cases
                batch_data.extend(page_cases)

            # Save batch
            if len(batch_data) >= BATCH_SIZE * 10 or terminate:  # 10 cases per page * BATCH_SIZE
                logger.info(f"Saving batch of {len(batch_data)} cases")
                save_to_csv(batch_data)
                batch_data = []

            # Check if we should terminate
            if terminate:
                break

            # Navigate to next page
            try:
                next_button = driver.find_element(
                    By.ID, "detayAramaSonuclar_next")
                if "disabled" in next_button.get_attribute("class"):
                    logger.info("No more pages available")
                    break

                next_button.click()
                time.sleep(PAGE_WAIT_TIME)
                current_page += 1
            except NoSuchElementException:
                logger.error("Next button not found. Checking for CAPTCHA...")
                if check_for_captcha(driver):
                    captcha_solved = wait_for_captcha_solution(driver)
                    if not captcha_solved:
                        break
                else:
                    logger.error(
                        "Navigation failed and no CAPTCHA detected. Terminating.")
                    break
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

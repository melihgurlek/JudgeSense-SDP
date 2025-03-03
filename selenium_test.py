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
import re

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
    """Improved CAPTCHA detection"""
    try:
        # Check if we're no longer on the expected results page
        results_table = driver.find_elements(
            By.CSS_SELECTOR, "#detayAramaSonuclar")
        if len(results_table) == 0:
            logger.info(
                "Results table not found - possible CAPTCHA or redirect")
            return True

        # Check for common CAPTCHA elements
        captcha_elements = [
            "iframe[src*='recaptcha']",
            "iframe[src*='captcha']",
            ".g-recaptcha",
            "#recaptcha",
            ".captcha-container",
            "form[action*='captcha']",
            "img[src*='captcha']"
        ]

        for selector in captcha_elements:
            if len(driver.find_elements(By.CSS_SELECTOR, selector)) > 0:
                logger.info(f"CAPTCHA element detected: {selector}")
                return True

        # Check for redirection to login/captcha page
        current_url = driver.current_url
        if "login" in current_url or "captcha" in current_url or "emsal" not in current_url:
            logger.info(f"Redirected to non-results URL: {current_url}")
            return True

        # Check page source for CAPTCHA-related keywords
        page_source = driver.page_source.lower()
        captcha_keywords = [
            "captcha", "robot", "human verification", "güvenlik doğrulaması", "doğrulama"]
        if any(keyword in page_source for keyword in captcha_keywords):
            logger.info("CAPTCHA-related text found in page source")
            return True

        return False
    except Exception as e:
        logger.warning(f"Error checking for CAPTCHA: {e}")
        return True  # Assume there's a CAPTCHA if we can't check properly


def wait_for_captcha_solution(driver, current_page):
    """Wait for the user to solve the CAPTCHA and return to results page"""
    logger.info(
        f"CAPTCHA detected! Please solve the CAPTCHA manually. Waiting up to {CAPTCHA_WAIT_TIME} seconds...")
    logger.info(f"Current page before CAPTCHA: {current_page}")

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

                # Check if we need to navigate back to the correct page
                # First, determine what page we're currently on
                try:
                    pagination_info = driver.find_element(
                        By.CSS_SELECTOR, ".pagination-info, .dataTables_info").text
                    # Extract current page using regex if available
                    page_match = re.search(
                        r"page\s+(\d+)", pagination_info.lower())
                    current_displayed_page = 1  # Default to page 1

                    if page_match:
                        current_displayed_page = int(page_match.group(1))

                    logger.info(
                        f"Current displayed page after CAPTCHA: {current_displayed_page}")

                    # If we're not on the correct page, we need to navigate there
                    if current_displayed_page != current_page:
                        logger.info(
                            f"Need to navigate from page {current_displayed_page} to page {current_page}")
                        return (True, current_displayed_page)
                except Exception as e:
                    logger.warning(f"Could not determine current page: {e}")

                return (True, None)  # CAPTCHA solved, no page info

            # Wait a bit before checking again
            time.sleep(5)
        except Exception as e:
            logger.warning(f"Error while waiting for CAPTCHA solution: {e}")
            time.sleep(5)

    logger.error("CAPTCHA wait time exceeded. Terminating script.")
    return (False, None)


def navigate_to_page(driver, target_page):
    """Navigate to a specific page number"""
    logger.info(f"Attempting to navigate to page {target_page}")

    try:
        # First, check what page we're currently on
        current_pagination = driver.find_element(
            By.CSS_SELECTOR, ".dataTables_info").text
        current_page_match = re.search(
            r"page\s+(\d+)", current_pagination.lower())
        current_page = 1
        if current_page_match:
            current_page = int(current_page_match.group(1))

        logger.info(
            f"Currently on page {current_page}, need to navigate to page {target_page}")

        if current_page == target_page:
            logger.info("Already on the correct page")
            return True

        # If we need to go backward, we might need to go to the first page first
        if target_page < current_page:
            logger.info("Need to go backward, returning to first page")
            first_page_button = driver.find_element(
                By.CSS_SELECTOR, ".paginate_button.first")
            if first_page_button and "disabled" not in first_page_button.get_attribute("class"):
                first_page_button.click()
                time.sleep(PAGE_WAIT_TIME)
                current_page = 1

        # Now navigate forward to the target page
        while current_page < target_page:
            next_button = driver.find_element(By.ID, "detayAramaSonuclar_next")
            if "disabled" in next_button.get_attribute("class"):
                logger.warning(
                    f"Cannot navigate to page {target_page}, reached the end at page {current_page}")
                return False

            next_button.click()
            time.sleep(PAGE_WAIT_TIME)
            current_page += 1
            logger.info(f"Navigated to page {current_page}")

            # Check for CAPTCHA after each navigation
            if check_for_captcha(driver):
                logger.warning("CAPTCHA detected during page navigation")
                captcha_result, _ = wait_for_captcha_solution(
                    driver, current_page)
                if not captcha_result:
                    return False

        return True
    except Exception as e:
        logger.error(f"Error navigating to page {target_page}: {e}")
        return False


def process_page(driver, wait, current_page):
    """Process all cases on a single page"""
    global terminate
    cases = []

    # First check if we need to handle CAPTCHA
    if check_for_captcha(driver):
        captcha_solved, new_page = wait_for_captcha_solution(
            driver, current_page)
        if not captcha_solved:
            return cases, current_page  # Return empty list if CAPTCHA not solved

        # If we need to navigate to a specific page after CAPTCHA
        if new_page is not None and new_page != current_page:
            navigate_success = navigate_to_page(driver, current_page)
            if not navigate_success:
                logger.warning(
                    f"Unable to navigate to page {current_page} after CAPTCHA")
                # Continue from the current page we're on
                current_page = new_page

    try:
        # Wait for rows to be present
        rows = WebDriverWait(driver, 30).until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "#detayAramaSonuclar tbody tr"))
        )

        if not rows:
            logger.warning(
                f"No rows found on page {current_page} - empty page")
            return [], current_page

        logger.info(f"Found {len(rows)} rows on page {current_page}")
    except TimeoutException:
        logger.error(f"Failed to find rows on page {current_page}")
        # Check again for CAPTCHA
        if check_for_captcha(driver):
            captcha_solved, new_page = wait_for_captcha_solution(
                driver, current_page)
            if not captcha_solved:
                return [], current_page

            # If we need to navigate to a specific page after CAPTCHA
            if new_page is not None and new_page != current_page:
                navigate_success = navigate_to_page(driver, current_page)
                if not navigate_success:
                    current_page = new_page

        return [], current_page

    for row_idx, row in enumerate(rows):
        if terminate:
            break

        retries = 0
        while retries < MAX_RETRIES and not terminate:
            try:
                columns = row.find_elements(By.TAG_NAME, "td")
                if len(columns) < 5:
                    logger.warning(
                        f"Row {row_idx+1} has insufficient columns: {len(columns)}")
                    break

                case_info = {
                    "Court Name": columns[0].text.strip(),
                    "Case Number": columns[1].text.strip(),
                    "Decision Number": columns[2].text.strip(),
                    "Decision Date": columns[3].text.strip(),
                    "Status": columns[4].text.strip(),
                    "Page": current_page
                }

                # Check if we already have valid data to avoid redundant clicks
                if all(len(val) > 0 for key, val in case_info.items() if key != "Page"):
                    logger.info(
                        f"Processing case {case_info['Case Number']} from page {current_page}")
                else:
                    logger.warning(
                        f"Case on row {row_idx+1} has empty fields: {case_info}")

                # Click to get explanation
                driver.execute_script("arguments[0].click();", row)

                # Wait for explanation to appear
                try:
                    explanation_element = WebDriverWait(driver, 20).until(
                        EC.visibility_of_element_located((By.ID, "kararAlani"))
                    )
                    explanation = explanation_element.text.strip()

                    # Check if explanation is empty or very short (likely an error)
                    if not explanation or len(explanation) < 10:
                        logger.warning(
                            f"Empty or very short explanation detected for case {case_info['Case Number']}")

                        # One empty case is enough to trigger CAPTCHA check
                        if check_for_captcha(driver):
                            captcha_solved, new_page = wait_for_captcha_solution(
                                driver, current_page)
                            if not captcha_solved:
                                return cases, current_page

                            # If we need to navigate to a specific page after CAPTCHA
                            if new_page is not None and new_page != current_page:
                                navigate_success = navigate_to_page(
                                    driver, current_page)
                                if not navigate_success:
                                    return cases, new_page

                        retries += 1
                        continue

                    case_info["Explanation"] = explanation
                    logger.info(
                        f"Successfully retrieved explanation for case {case_info['Case Number']}")

                except TimeoutException:
                    # If we can't find the explanation area, check for CAPTCHA
                    logger.warning(
                        f"No explanation area found for case {case_info['Case Number']}. Checking for CAPTCHA...")
                    if check_for_captcha(driver):
                        captcha_solved, new_page = wait_for_captcha_solution(
                            driver, current_page)
                        if not captcha_solved:
                            return cases, current_page

                        # If we need to navigate to a specific page after CAPTCHA
                        if new_page is not None and new_page != current_page:
                            navigate_success = navigate_to_page(
                                driver, current_page)
                            if not navigate_success:
                                return cases, new_page
                    retries += 1
                    continue

                cases.append(case_info)
                break  # Success - exit retry loop

            except Exception as e:
                logger.warning(
                    f"Retry {retries+1}/{MAX_RETRIES} for case on row {row_idx+1}: {e}")
                retries += 1
                time.sleep(2)
                if retries >= MAX_RETRIES:
                    logger.error(
                        f"Failed to process case on row {row_idx+1} after {MAX_RETRIES} attempts")

    # If we didn't get any valid cases with explanations, this is likely a CAPTCHA issue
    if not cases:
        logger.warning(
            f"No valid cases obtained from page {current_page}. Checking for CAPTCHA...")
        if check_for_captcha(driver):
            captcha_solved, new_page = wait_for_captcha_solution(
                driver, current_page)
            if not captcha_solved:
                return cases, current_page

            # If we need to navigate to a specific page after CAPTCHA
            if new_page is not None and new_page != current_page:
                navigate_success = navigate_to_page(driver, current_page)
                if not navigate_success:
                    return cases, new_page

    return cases, current_page


def reset_search(driver, wait, current_page):
    """Reset search and navigate back to the current page"""
    try:
        logger.info("Resetting search...")

        # Navigate to the main page
        driver.get("https://emsal.uyap.gov.tr/#")
        time.sleep(PAGE_WAIT_TIME * 2)  # Extra wait time for initial load

        # Check for CAPTCHA
        if check_for_captcha(driver):
            captcha_solved, _ = wait_for_captcha_solution(
                driver, 1)  # Start at page 1
            if not captcha_solved:
                return False

        # Perform search
        try:
            search_box = wait.until(
                EC.presence_of_element_located((By.TAG_NAME, "input")))
            search_box.clear()
            search_box.send_keys("Hukuk" + Keys.RETURN)
            time.sleep(PAGE_WAIT_TIME * 2)  # Wait longer for search results
        except Exception as e:
            logger.error(f"Failed to perform search: {e}")
            return False

        # Check if search was successful
        if len(driver.find_elements(By.CSS_SELECTOR, "#detayAramaSonuclar")) == 0:
            logger.error("Search did not return results table")
            return False

        # Navigate to the desired page
        if current_page > 1:
            logger.info(f"Navigating to page {current_page} after reset")
            return navigate_to_page(driver, current_page)

        return True
    except Exception as e:
        logger.error(f"Error resetting search: {e}")
        return False


def main():
    global terminate

    # Initialize browser with more undetectable options
    options = webdriver.ChromeOptions()
    # Never use headless mode with CAPTCHAs

    # Add options that might help bypass CAPTCHA detection
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Set user agent to appear more like a regular browser
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36")

    driver = webdriver.Chrome(options=options)
    # Set normal window size to appear more like a human user
    driver.set_window_size(1366, 768)

    # Execute CDP commands to modify navigator.webdriver property
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    # Add cookies to simulate a returning user
    driver.execute_script("document.cookie = 'visited=true; path=/';")

    wait = WebDriverWait(driver, 20)

    last_page = get_last_page()
    current_page = last_page + 1 if last_page > 0 else 1
    logger.info(f"Starting from page {current_page}")

    try:
        # Navigate to initial URL
        driver.get("https://emsal.uyap.gov.tr/#")
        time.sleep(PAGE_WAIT_TIME * 2)  # Give extra time for initial load

        # Check for CAPTCHA on initial load
        if check_for_captcha(driver):
            captcha_solved, _ = wait_for_captcha_solution(
                driver, 1)  # Start at page 1
            if not captcha_solved:
                logger.error("Initial CAPTCHA not solved. Exiting.")
                driver.quit()
                return

        # Perform initial search
        try:
            search_box = wait.until(
                EC.presence_of_element_located((By.TAG_NAME, "input")))
            search_box.send_keys("Hukuk" + Keys.RETURN)
            time.sleep(PAGE_WAIT_TIME * 2)  # Wait longer for search results
        except Exception as e:
            logger.error(f"Failed to perform initial search: {e}")
            driver.quit()
            return

        # Navigate to the starting page if needed
        if current_page > 1:
            logger.info(f"Navigating to starting page {current_page}")
            if not navigate_to_page(driver, current_page):
                logger.error(
                    f"Failed to navigate to starting page {current_page}. Exiting.")
                driver.quit()
                return

        batch_data = []

        while not terminate:
            logger.info(f"Processing page {current_page}")

            # Process current page and get updated current_page if it changed due to CAPTCHA
            page_cases, updated_page = process_page(driver, wait, current_page)

            # Check if current_page was updated due to CAPTCHA navigation issues
            if updated_page != current_page:
                logger.warning(
                    f"Page changed from {current_page} to {updated_page} during processing")
                current_page = updated_page

            # Check if we got any cases
            if not page_cases:
                logger.warning(f"No cases found on page {current_page}.")

                # If empty page, reset search or try next page
                search_reset = reset_search(driver, wait, current_page)
                if not search_reset:
                    logger.error("Failed to reset search. Trying next page...")

                    # Try moving to next page
                    try:
                        next_button = driver.find_element(
                            By.ID, "detayAramaSonuclar_next")
                        if "disabled" in next_button.get_attribute("class"):
                            logger.info("No more pages available")
                            terminate = True
                            break

                        next_button.click()
                        time.sleep(PAGE_WAIT_TIME)
                        current_page += 1
                        logger.info(f"Moved to next page: {current_page}")
                        continue
                    except Exception as e:
                        logger.error(
                            f"Failed to navigate to next page after empty results: {e}")
                        terminate = True
                        break
            else:
                logger.info(
                    f"Successfully processed {len(page_cases)} cases on page {current_page}")
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
                logger.info(f"Navigated to page {current_page}")
            except NoSuchElementException:
                logger.error("Next button not found. Checking for CAPTCHA...")
                if check_for_captcha(driver):
                    captcha_solved, new_page = wait_for_captcha_solution(
                        driver, current_page)
                    if not captcha_solved:
                        break

                    # If we need to navigate to a specific page after CAPTCHA
                    if new_page is not None and new_page != current_page:
                        navigate_success = navigate_to_page(
                            driver, current_page)
                        if not navigate_success:
                            current_page = new_page
                else:
                    logger.error(
                        "Navigation failed and no CAPTCHA detected. Terminating.")
                    break
            except Exception as e:
                logger.error(f"Failed to navigate to next page: {e}")

                # Check for CAPTCHA here as well
                if check_for_captcha(driver):
                    captcha_solved, new_page = wait_for_captcha_solution(
                        driver, current_page)
                    if not captcha_solved:
                        break

                    # If we need to navigate to a specific page after CAPTCHA
                    if new_page is not None:
                        current_page = new_page
                else:
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

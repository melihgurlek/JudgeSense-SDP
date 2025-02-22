from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import pandas as pd
import sys
import random
from selenium.webdriver.common.action_chains import ActionChains

# Set up Selenium WebDriver
options = webdriver.ChromeOptions()
# options.add_argument("--headless")  # Run in background (remove for debugging)
driver = webdriver.Chrome(options=options)

# Open the website
url = "https://emsal.uyap.gov.tr/#"
driver.get(url)
wait = WebDriverWait(driver, 10)

# Step 1: Perform Search
search_box = wait.until(EC.presence_of_element_located((By.TAG_NAME, "input")))

search_box.send_keys("Hukuk")  # Enter search term
search_box.send_keys(Keys.RETURN)  # Press Enter or use below
time.sleep(3)  # Wait for results to load

# Data Storage
cases = []

try:
    while True:
        # Step 2: Extract all cases from the current page
        rows = driver.find_elements(
            By.CSS_SELECTOR, "#detayAramaSonuclar tbody tr")

        for row in rows:
            columns = row.find_elements(By.TAG_NAME, "td")
            if len(columns) < 5:
                continue  # Skip rows that don't match expected structure

            court_name = columns[0].text
            case_number = columns[1].text
            decision_number = columns[2].text
            decision_date = columns[3].text
            status = columns[4].text

            time.sleep(random.uniform(2, 5))
            driver.execute_script("window.scrollBy(0, 200);")
            time.sleep(random.uniform(1, 3))
            # Click the row to load the explanation
            row.click()
            time.sleep(2)  # Wait for content to load

            # Get Explanation Text
            explanation_div = wait.until(
                EC.presence_of_element_located((By.ID, "kararAlani")))
            explanation_text = explanation_div.text

            # Store Data
            cases.append({
                "Court Name": court_name,
                "Case Number": case_number,
                "Decision Number": decision_number,
                "Decision Date": decision_date,
                "Status": status,
                "Explanation": explanation_text
            })

        # Step 3: Go to the next page (if available)
        try:
            next_button = driver.find_element(By.ID, "detayAramaSonuclar_next")
            ActionChains(driver).move_to_element(next_button).perform()
            time.sleep(random.uniform(2, 5))
            if "disabled" in next_button.get_attribute("class"):
                break  # Stop if next button is disabled
            next_button.click()
            time.sleep(3)  # Wait for new page to load
        except:
            break  # If button is not found, stop pagination

except Exception as e:
    print(f"An error occurred: {e}")

finally:
    # This block will execute when the browser is closed or the script ends
    try:
        # Save collected data to CSV
        df = pd.DataFrame(cases)
        df.to_csv("legal_cases.csv", index=False, encoding="utf-8")
        print("Scraping Complete! Data saved to 'legal_cases.csv'.")
    except Exception as e:
        print(f"Failed to save data: {e}")

    # Close the browser
    driver.quit()
    sys.exit()

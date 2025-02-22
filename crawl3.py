from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import pandas as pd
import sys
import random


options = webdriver.ChromeOptions()
# options.add_argument("--headless")
driver = webdriver.Chrome(options=options)

url = "https://emsal.uyap.gov.tr/#"
driver.get(url)
wait = WebDriverWait(driver, 10)

search_box = wait.until(EC.presence_of_element_located((By.TAG_NAME, "input")))

search_box.send_keys("Hukuk")
search_box.send_keys(Keys.RETURN)
time.sleep(3)

cases = []

try:
    while True:
        rows = driver.find_elements(
            By.CSS_SELECTOR, "#detayAramaSonuclar tbody tr")

        for row in rows:
            columns = row.find_elements(By.TAG_NAME, "td")
            if len(columns) < 5:
                continue

            court_name = columns[0].text
            case_number = columns[1].text
            decision_number = columns[2].text
            decision_date = columns[3].text
            status = columns[4].text

            row.click()
            time.sleep(2)

            explanation_div = wait.until(
                EC.presence_of_element_located((By.ID, "kararAlani")))
            explanation_text = explanation_div.text

            cases.append({
                "Court Name": court_name,
                "Case Number": case_number,
                "Decision Number": decision_number,
                "Decision Date": decision_date,
                "Status": status,
                "Explanation": explanation_text
            })

        try:
            next_button = driver.find_element(By.ID, "detayAramaSonuclar_next")
            if "disabled" in next_button.get_attribute("class"):
                break
            next_button.click()
            time.sleep(3)
        except:
            break

except Exception as e:
    print(f"An error occurred: {e}")

finally:
    try:
        df = pd.DataFrame(cases)
        df.to_csv("legal_cases.csv", index=False, encoding="utf-8")
        print("Scraping Complete! Data saved to 'legal_cases.csv'.")
    except Exception as e:
        print(f"Failed to save data: {e}")

    driver.quit()
    sys.exit()

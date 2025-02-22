import requests
import time
import pandas as pd
import os
import keyboard
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

# Headers copied from browser's DevTools
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
    "Content-Type": "application/json; charset=UTF-8",
    "Referer": "https://emsal.uyap.gov.tr/index",
    "X-Requested-With": "XMLHttpRequest"
}

# CSV File Name
CSV_FILE = "legal_cases.csv"

# 🛠️ Step 1: Check last completed page
if os.path.exists(CSV_FILE):
    try:
        df = pd.read_csv(CSV_FILE)
        last_page = df["Page"].max()  # Find last page number in the CSV
    except:
        last_page = 0  # If file is corrupted, start from the beginning
else:
    last_page = 0  # If file doesn't exist, start from page 1

print(f"🔄 Resuming from page {last_page + 1}...")

# Start a session to maintain cookies
session = requests.Session()

# Step 2: Send Search Request
search_payload = {
    "data": {
        "aranan": "Hukuk",
        "arananKelime": "Hukuk"
    }
}
search_url = "https://emsal.uyap.gov.tr/arama"
session.post(search_url, json=search_payload, headers=HEADERS)

# Step 3: Fetch Case List
cases = []
page = last_page + 1  # Resume from last saved page

# Function to fetch case explanation


def get_explanation(case_id):
    explanation_url = f"https://emsal.uyap.gov.tr/getDokuman?id={case_id}"

    while True:  # Retry loop for CAPTCHA on explanation request
        explanation_response = session.get(explanation_url, headers=HEADERS)

        if explanation_response.status_code != 200:
            print(
                f"⚠️ Failed to fetch explanation for {case_id}, retrying in 5 seconds...")
            time.sleep(5)
            continue  # Retry request

        explanation_json = explanation_response.json()

        if explanation_json["metadata"]["FMC"] == "ADALET_RUNTIME_EXCEPTION":
            print(
                f"🚨 CAPTCHA detected while fetching explanation for case {case_id}! Waiting 10 seconds...")
            time.sleep(10)
            continue  # Retry

        raw_html = explanation_json.get("data", "")
        soup = BeautifulSoup(raw_html, "html.parser")
        return soup.get_text(separator="\n").strip()


while True:
    print(f"Scraping page {page}...")

    # Check for early termination
    if keyboard.is_pressed("q"):
        print("❌ Stopping early, saving progress...")
        df.to_csv(CSV_FILE, mode="a", header=False,
                  index=False, encoding="utf-8")
        exit()

    # Corrected Payload
    case_list_payload = {
        "data": {
            "aranan": "Hukuk",
            "arananKelime": "Hukuk",
            "pageSize": 10,
            "pageNumber": page
        }
    }

    case_list_url = "https://emsal.uyap.gov.tr/aramalist"

    while True:  # Loop to keep retrying on CAPTCHA
        response = session.post(
            case_list_url, json=case_list_payload, headers=HEADERS)

        if response.status_code != 200:
            print("⚠️ Failed to fetch cases, retrying in 5 seconds...")
            time.sleep(5)
            continue  # Retry request

        case_data = response.json()

        # 🚨 Check if CAPTCHA is triggered
        if case_data["metadata"]["FMC"] == "ADALET_RUNTIME_EXCEPTION":
            print(
                f"🚨 CAPTCHA detected on page {page}! Waiting 10 seconds before retrying...")
            time.sleep(10)  # Wait 10 seconds and retry
            continue  # Retry the request from the same page

        break  # If no CAPTCHA, exit retry loop and continue scraping

    cases_list = case_data["data"]["data"]  # ✅ Extract case list

    if not cases_list:
        print("No more cases found, stopping.")
        break

    # Fetch explanations in parallel using threads (faster!)
    with ThreadPoolExecutor(max_workers=5) as executor:
        explanations = list(executor.map(
            get_explanation, [case["id"] for case in cases_list]))

    for case, explanation_text in zip(cases_list, explanations):
        cases.append({
            "Page": page,  # Save page number for resuming
            "Court Name": case["daire"],
            "Case Number": case["esasNo"],
            "Decision Number": case["kararNo"],
            "Decision Date": case["kararTarihi"],
            "Status": case["durum"],
            "Explanation": explanation_text
        })

    # Step 5: Save Progress to CSV After Each Page
    df = pd.DataFrame(cases)
    if os.path.exists(CSV_FILE):
        df.to_csv(CSV_FILE, mode="a", header=False,
                  index=False, encoding="utf-8")  # Append
    else:
        df.to_csv(CSV_FILE, index=False, encoding="utf-8")  # Create new file

    print(f"✅ Data saved after page {page}")

    page += 1  # Move to next page

print("✅ Scraping Complete!")

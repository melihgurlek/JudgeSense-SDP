import requests
import time
import pandas as pd
from bs4 import BeautifulSoup

# Headers copied from browser's DevTools
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
    "Content-Type": "application/json; charset=UTF-8",
    "Referer": "https://emsal.uyap.gov.tr/index",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin"
}

# Start a session to maintain cookies
session = requests.Session()

# Step 1: Send Search Request
search_payload = {
    "data": {
        "aranan": "Hukuk",
        "arananKelime": "Hukuk"
    }
}
search_url = "https://emsal.uyap.gov.tr/arama"
session.post(search_url, json=search_payload, headers=HEADERS)

# Step 2: Fetch Case List for page 1 only
cases = []

# Corrected Payload for page 1
case_list_payload = {
    "data": {
        "aranan": "Hukuk",
        "arananKelime": "Hukuk",
        "pageSize": 10,  # Number of results per page
        "pageNumber": 1  # Current page number set to 1
    }
}

case_list_url = "https://emsal.uyap.gov.tr/aramalist"
response = session.post(
    case_list_url, json=case_list_payload, headers=HEADERS)

if response.status_code != 200:
    print("Failed to fetch cases, stopping.")
else:
    case_data = response.json()

    # 🔥 FIX: Access the correct data structure
    cases_list = case_data["data"]["data"]  # ✅ Extract case list

    if not cases_list:  # If there's no case data, stop
        print("No cases found, stopping.")
    else:
        for case in cases_list:
            case_id = case["id"]  # Extract case ID
            court_name = case["daire"]  # ✅ Correct key for court name
            case_number = case["esasNo"]  # ✅ Correct key for case number
            # ✅ Correct key for decision number
            decision_number = case["kararNo"]
            # ✅ Correct key for decision date
            decision_date = case["kararTarihi"]
            status = case["durum"]  # ✅ Correct key for status

            # Step 3: Fetch Case Explanation
            explanation_url = f"https://emsal.uyap.gov.tr/getDokuman?id={case_id}"
            explanation_response = session.get(
                explanation_url, headers=HEADERS)

            if explanation_response.status_code == 200:
                raw_html = explanation_response.json()[
                    "data"]  # Extract raw HTML
                # Parse with BeautifulSoup
                soup = BeautifulSoup(raw_html, "html.parser")
                explanation_text = soup.get_text(
                    separator="\n").strip()  # Extract clean text
            else:
                explanation_text = "N/A"

            # Store Case Data
            cases.append({
                "Court Name": court_name,
                "Case Number": case_number,
                "Decision Number": decision_number,
                "Decision Date": decision_date,
                "Status": status,
                "Explanation": explanation_text
            })

            # Respect server with a short delay
            time.sleep(2)

# Step 4: Save to CSV
df = pd.DataFrame(cases)
df.to_csv("legal_cases_page_1.csv", index=False, encoding="utf-8")
print("Scraping Complete! Data saved to 'legal_cases_page_1.csv'.")

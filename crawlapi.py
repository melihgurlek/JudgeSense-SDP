import requests
import time
import pandas as pd

# Headers (use same headers from browser)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json; charset=UTF-8",
    "Referer": "https://emsal.uyap.gov.tr/index",
    "X-Requested-With": "XMLHttpRequest"
}

# Start a session to maintain cookies
session = requests.Session()

session.get("https://emsal.uyap.gov.tr/index", headers=HEADERS)  # Get session
cookies = session.cookies.get_dict()
print("Session Cookies:", cookies)  # Check if JSESSIONID is set

HEADERS["Cookie"] = f"JSESSIONID={cookies.get('JSESSIONID', '')}"


# Step 1: Send Search Request
search_payload = {"search_term": "Hukuk"}  # Adjust as needed
search_url = "https://emsal.uyap.gov.tr/arama"
session.post(search_url, json=search_payload, headers=HEADERS)

# Step 2: Fetch Case List
cases = []
page = 1

while True:
    print(f"Scraping page {page}...")

    case_list_url = "https://emsal.uyap.gov.tr/aramalist"
    # Modify if API uses different pagination
    case_list_payload = {"page": page}

    response = session.post(
        case_list_url, json=case_list_payload, headers=HEADERS)

    if response.status_code != 200:
        print("Failed to fetch cases, stopping.")
        break

    case_data = response.json()

    if not case_data["cases"]:  # Stop if no more cases
        break

    for case in case_data["cases"]:
        case_id = case["id"]  # Extract case ID
        court_name = case["court"]
        case_number = case["case_number"]
        decision_number = case["decision_number"]
        decision_date = case["decision_date"]
        status = case["status"]

        # Step 3: Fetch Case Explanation
        explanation_url = f"https://emsal.uyap.gov.tr/getDokuman?id={case_id}"
        explanation_response = session.get(explanation_url, headers=HEADERS)

        if explanation_response.status_code == 200:
            explanation_text = explanation_response.json()[
                "content"]  # Adjust if needed
        else:
            explanation_text = "N/A"

        # Save Case
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

    page += 1

# Step 4: Save to CSV
df = pd.DataFrame(cases)
df.to_csv("legal_cases.csv", index=False, encoding="utf-8")
print("Scraping Complete! Data saved to 'legal_cases.csv'.")

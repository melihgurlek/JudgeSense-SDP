import requests
import time
import pandas as pd
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json; charset=UTF-8",
    "Referer": "https://emsal.uyap.gov.tr/detay",
    "Origin": "https://emsal.uyap.gov.tr",
    "X-Requested-With": "XMLHttpRequest",
    "Accept-Language": "tr-TR,tr;q=0.9",
    "Accept-Encoding": "gzip, deflate, br"
}


def get_case_explanation(session, case_id):
    """Enhanced explanation fetcher with proper headers"""
    url = f"https://emsal.uyap.gov.tr/getDokuman?id={case_id}"

    try:
        response = session.get(
            url,
            headers={
                **HEADERS,
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Referer": f"https://emsal.uyap.gov.tr/detay?id={case_id}"
            },
            timeout=10
        )

        # Debug response
        print(f"Case {case_id} Response Status: {response.status_code}")
        print(f"Response Headers: {response.headers}")

        if response.status_code == 200:
            try:
                # Handle as JSON first
                return response.json().get("content", "No content found")
            except json.JSONDecodeError:
                # Fallback to text handling
                return response.text.strip() or "Empty response"
        return "Non-200 status"

    except Exception as e:
        return f"Request failed: {str(e)[:50]}"


# Full workflow
session = requests.Session()

# 1. Initial navigation sequence
session.get("https://emsal.uyap.gov.tr/index", headers=HEADERS)
time.sleep(1)

# 2. Search authentication
search_payload = {"data": {"aranan": "Hukuk", "arananKelime": "Hukuk"}}
session.post("https://emsal.uyap.gov.tr/arama",
             json=search_payload, headers=HEADERS)
time.sleep(1)

# 3. Get case list
case_list = session.post(
    "https://emsal.uyap.gov.tr/aramalist",
    json={"data": {"aranan": "Hukuk", "arananKelime": "Hukuk",
                   "pageSize": 10, "pageNumber": 1}},
    headers=HEADERS
).json()["data"]["data"]

# 4. Process cases
results = []
for case in case_list:
    results.append({
        "Court Name": case.get("daire"),
        "Case Number": case.get("esasNo"),
        "Decision Number": case.get("kararNo"),
        "Decision Date": case.get("kararTarihi"),
        "Status": case.get("durum"),
        "Explanation": get_case_explanation(session, case["id"])
    })
    time.sleep(2.5)  # Critical for server compliance

# Save results
pd.DataFrame(results).to_csv("uyap_cases_final.csv",
                             index=False, encoding="utf-8-sig")
print("Successfully scraped", len(results), "cases")

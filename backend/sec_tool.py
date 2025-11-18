# sec_tool.py
"""
SEC EDGAR helpers (safe, API-only, no scraping).
Provides:
- company_filings_index(cik) -> dict  (submissions index JSON)
- fetch_filing_text(document_url) -> str (fetch plain-text filing)
"""

import requests
from typing import Dict, Any
from requests.exceptions import RequestException

USER_AGENT = "bytical-research-bot/1.0 (+https://bytical.ai)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

def company_filings_index(cik: str) -> Dict[str, Any]:
    """
    Return the EDGAR submissions index for the given CIK.
    CIK may be a number or zero-padded string (function zero-pads to 10 digits).
    Example: company_filings_index('320193') or company_filings_index('0000320193')
    """
    cik_str = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_str}.json"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except RequestException as e:
        # Return structured error so caller can handle gracefully
        return {"error": "request_failed", "message": str(e), "url": url}

def fetch_filing_text(document_url: str) -> str:
    """
    Fetches a filing document (preferably the plain .txt file URL) and returns its text.
    If the request fails, returns a dictionary-like string with the error.
    """
    try:
        resp = requests.get(document_url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        # Return raw text (SEC provides plain text files)
        return resp.text
    except RequestException as e:
        return f"ERROR_FETCHING_DOCUMENT: {str(e)}"

# financial_tool.py
"""
Free financial helpers without scraping.
- get_yahoo_summary(symbol)
- get_stock_price(symbol)
- get_sec_companyfacts(cik)
"""
import os
import time
import requests
from typing import Dict, Any

USER_AGENT = os.getenv("TOOL_USER_AGENT", "bytical-research-bot/1.0")
HEADERS = {"User-Agent": USER_AGENT}

def _get_json(url: str, params: dict = None, timeout: int = 10) -> Dict[str, Any]:
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(1 + attempt)
    return {"error": f"Failed GET {url}"}

def get_yahoo_summary(symbol: str) -> Dict[str, Any]:
    url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    params = {"modules": "price,summaryProfile,financialData,defaultKeyStatistics"}
    return _get_json(url, params=params)

def get_stock_price(symbol: str) -> Dict[str, Any]:
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    return _get_json(url, params={"symbols": symbol})

def get_sec_companyfacts(cik: str) -> Dict[str, Any]:
    cik = str(cik).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    return _get_json(url)

# financial_tool.py
"""
Upgraded financial tool (free endpoints only).
Provides:
- get_yahoo_full_summary(symbol): many modules (profile, financials)
- get_yahoo_historical(symbol, period_days=365, interval='1d'): returns OHLC time-series + direct download URL
- get_yahoo_statements(symbol, statement='incomeStatement', years=5): wrapper to extract statements
- get_yahoo_modules(symbol, modules_list): general helper
All returned objects include `__source_link` fields with direct URLs when available.
"""
import os
import time
import requests
from typing import Dict, Any, List
from datetime import datetime, timedelta
USER_AGENT = os.getenv("TOOL_USER_AGENT", "bytical-research-bot/1.0")
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}

def _get_json(url: str, params: dict = None, tries: int = 3, timeout: int = 10) -> Dict[str, Any]:
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(0.5 + i)
    return {"error": str(last), "__request_url": url}

def get_yahoo_modules(symbol: str, modules: List[str]) -> Dict[str, Any]:
    """
    Generic call for quoteSummary modules.
    Example modules: ["price","summaryProfile","financialData","incomeStatementHistory","balanceSheetHistory"]
    Adds __source_link pointing to Yahoo quote page for traceability.
    """
    base = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    params = {"modules": ",".join(modules)}
    data = _get_json(base, params=params)
    data["__source_link"] = f"https://finance.yahoo.com/quote/{symbol}"
    return data

def get_yahoo_full_summary(symbol: str) -> Dict[str, Any]:
    modules = [
        "price","summaryProfile","financialData","defaultKeyStatistics",
        "incomeStatementHistory","balanceSheetHistory","cashflowStatementHistory","earnings"
    ]
    return get_yahoo_modules(symbol, modules)

def get_yahoo_historical(symbol: str, period_days: int = 365, interval: str = '1d') -> Dict[str, Any]:
    """
    Returns OHLC time-series (CSV->parsed) along with direct download link.
    Uses the public Yahoo 'download' endpoint.
    period2 = now, period1 = now - period_days
    Returns:
      {
        "history": [{"date":"YYYY-MM-DD","open":..,"high":..,"low":..,"close":..,"volume":..}, ...],
        "__download_url": "...",
        "__source_link": "https://finance.yahoo.com/quote/{symbol}/history"
      }
    """
    now = int(time.time())
    start = int((datetime.utcnow() - timedelta(days=period_days)).timestamp())
    url = f"https://query1.finance.yahoo.com/v7/finance/download/{symbol}"
    params = {"period1": start, "period2": now, "interval": interval, "events": "history", "includeAdjustedClose":"true"}
    # attempt to fetch CSV
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        csv_text = r.text
        # parse CSV lines into objects
        rows = []
        lines = [l for l in csv_text.splitlines() if l.strip()]
        if lines:
            hdr = lines[0].split(',')
            for ln in lines[1:]:
                cols = ln.split(',')
                if len(cols) != len(hdr): 
                    continue
                row = dict(zip(hdr, cols))
                # convert to typed values when possible
                try:
                    row_parsed = {
                        "date": row.get("Date"),
                        "open": float(row.get("Open")) if row.get("Open") not in ("", "null", "NA") else None,
                        "high": float(row.get("High")) if row.get("High") not in ("", "null", "NA") else None,
                        "low": float(row.get("Low")) if row.get("Low") not in ("", "null", "NA") else None,
                        "close": float(row.get("Close")) if row.get("Close") not in ("", "null", "NA") else None,
                        "adjclose": float(row.get("Adj Close")) if row.get("Adj Close") not in ("", "null", "NA") else None,
                        "volume": int(row.get("Volume")) if row.get("Volume") not in ("", "null", "NA") else None
                    }
                except Exception:
                    row_parsed = {"date": row.get("Date"), "raw": row}
                rows.append(row_parsed)
        return {
            "history": rows,
            "__download_url": r.url,
            "__source_link": f"https://finance.yahoo.com/quote/{symbol}/history"
        }
    except Exception as e:
        return {"error": str(e), "__request_url": url, "__params": params}

def get_yahoo_statements(symbol: str, years: int = 5) -> Dict[str, Any]:
    """
    Convenience: returns income, balance, cashflow with raw arrays if available.
    """
    data = get_yahoo_modules(symbol, ["incomeStatementHistory", "balanceSheetHistory", "cashflowStatementHistory", "earnings"])
    out = {}
    try:
        out["incomeStatementHistory"] = data.get("quoteSummary", {}).get("result", [{}])[0].get("incomeStatementHistory", {})
        out["balanceSheetHistory"] = data.get("quoteSummary", {}).get("result", [{}])[0].get("balanceSheetHistory", {})
        out["cashflowStatementHistory"] = data.get("quoteSummary", {}).get("result", [{}])[0].get("cashflowStatementHistory", {})
        out["earnings"] = data.get("quoteSummary", {}).get("result", [{}])[0].get("earnings", {})
    except Exception:
        out["error"] = "could_not_parse"
    out["__source_link"] = f"https://finance.yahoo.com/quote/{symbol}/financials"
    return out

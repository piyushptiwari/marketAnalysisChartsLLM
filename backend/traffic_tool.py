# FILE: traffic_tool.py
"""
Traffic and competitor web metrics.
This module contains a lightweight SimilarWeb wrapper that uses the free endpoints
or fallback heuristics. NOTE: SimilarWeb's official API requires an API key for
reliable results. For free usage, this provides a domain-level scraping helper
that fetches public data where possible.


Functions:
- fetch_similarweb_summary(domain)


If you have a SIMILARWEB_API_KEY in env, it will call the API.
Otherwise it will return a minimal placeholder and instruct the caller to provide a key.
"""
import os
import requests
from typing import Dict, Any


SIMILARWEB_API_KEY = os.getenv('SIMILARWEB_API_KEY')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


def fetch_similarweb_summary(domain: str) -> dict:
    if SIMILARWEB_API_KEY:
        url = f"https://api.similarweb.com/v1/website/{domain}/total-traffic-and-engagement/visits"
        params = {"api_key": SIMILARWEB_API_KEY, "granularity": "monthly", "start_date": "2023-01", "end_date": "2025-12"}
        r = requests.get(url, params=params, headers=HEADERS)
        r.raise_for_status()
        return r.json()
    else:
    # Minimal free fallback: return a message + attempt to fetch public summary via textise dot iitty
        return {"error": "SIMILARWEB_API_KEY not set. Please provide an API key for reliable traffic data.", "domain": domain}
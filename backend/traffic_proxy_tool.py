# traffic_proxy_tool.py
"""
Traffic proxy using Google Trends only – no scraping.
"""
from google_trends_tool import get_interest_over_time
from typing import List, Dict, Any

def traffic_interest(keywords: List[str], timeframe="today 12-m") -> Dict[str, Any]:
    return get_interest_over_time(keywords, timeframe=timeframe)

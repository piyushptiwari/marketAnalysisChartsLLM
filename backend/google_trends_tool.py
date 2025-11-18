# google_trends_tool.py
from pytrends.request import TrendReq
from typing import List, Dict, Any
from datetime import datetime

_py = None

def _ensure():
    global _py
    if _py is None:
        _py = TrendReq(hl='en-US', tz=360)

def build_trends_explore_url(keywords: List[str], timeframe: str = "today 12-m", geo: str = "", category: int = 0) -> str:
    # Build a Trends Explore link with query and optional geo
    q = ",".join(keywords) if isinstance(keywords, list) else keywords
    base = "https://trends.google.com/trends/explore"
    params = f"?q={q}&date={timeframe}"
    if geo:
        params += f"&geo={geo}"
    if category:
        params += f"&cat={category}"
    return base + params

def get_interest_over_time(keywords: List[str], timeframe: str = 'today 12-m', geo: str = '', category: int = 0) -> Dict[str, Any]:
    """
    Returns:
    {
      "interest": { "keyword1": {"2025-01-01": 10, ...}, "keyword2": {...} },
      "__explore_url": "https://trends.google.com/..."
    }
    """
    _ensure()
    kw = keywords if isinstance(keywords, list) else [keywords]
    _py.build_payload(kw, timeframe=timeframe, geo=geo, cat=category)
    df = _py.interest_over_time()
    if df is None or df.empty:
        return {"error": "no data", "__explore_url": build_trends_explore_url(kw, timeframe, geo, category)}
    out = {}
    # df index is datetime — convert to ISO date strings
    for col in df.columns:
        if col == "isPartial": 
            continue
        series = df[col]
        d = {}
        for idx, val in series.items():
            # idx may be Timestamp; format as YYYY-MM-DD or YYYY-MM if monthly
            try:
                if hasattr(idx, "date"):
                    key = idx.date().isoformat()
                else:
                    key = str(idx)
            except Exception:
                key = str(idx)
            d[key] = int(val)
        out[col] = d
    return {"interest": out, "__explore_url": build_trends_explore_url(kw, timeframe, geo, category)}

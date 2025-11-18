# google_trends_tool.py
from pytrends.request import TrendReq
from typing import Dict, Any, List

_py = None

def _ensure():
    global _py
    if _py is None:
        _py = TrendReq(hl='en-US', tz=360)

def get_interest_over_time(keywords: List[str], timeframe="today 12-m", geo="") -> Dict[str, Any]:
    _ensure()
    _py.build_payload(keywords, timeframe=timeframe, geo=geo)
    df = _py.interest_over_time()
    if df is None or df.empty:
        return {"error": "no data"}
    out = {}
    for col in df.columns:
        out[col] = df[col].astype(int).to_dict()
    return out

def get_related_queries(keyword: str) -> Dict[str, Any]:
    _ensure()
    _py.build_payload([keyword])
    return _py.related_queries()

# news_tool.py
import feedparser
from typing import List, Dict, Any

def google_news_rss(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    q = query.replace(" ", "+")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)
    items = feed.get("entries", [])[:limit]
    out = []
    for e in items:
        out.append({
            "title": e.get("title"),
            "link": e.get("link"),
            "published": e.get("published"),
            "summary": e.get("summary"),
        })
    return out

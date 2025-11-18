# reddit_tool.py
import feedparser
from typing import List, Dict, Any

def reddit_search_rss(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    q = query.replace(" ", "+")
    url = f"https://www.reddit.com/search.rss?q={q}"
    feed = feedparser.parse(url)
    out = []
    for e in feed.get("entries", [])[:limit]:
        out.append({
            "title": e.get("title"),
            "link": e.get("link"),
            "summary": e.get("summary"),
            "published": e.get("published"),
        })
    return out

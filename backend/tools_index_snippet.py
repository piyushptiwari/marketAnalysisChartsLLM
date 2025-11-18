# tools_index_snippet.py
import financial_tool
import sec_tool
import google_trends_tool
import news_tool
import reddit_tool
import traffic_proxy_tool

tools_available = {
    "get_yahoo_summary": financial_tool.get_yahoo_summary,
    "get_stock_price": financial_tool.get_stock_price,
    "get_sec_companyfacts": financial_tool.get_sec_companyfacts,
    "company_filings_index": sec_tool.company_filings_index,
    "fetch_filing_text": sec_tool.fetch_filing_text,
    "google_trends_interest": google_trends_tool.get_interest_over_time,
    "google_news_rss": news_tool.google_news_rss,
    "reddit_search_rss": reddit_tool.reddit_search_rss,
    "traffic_interest": traffic_proxy_tool.traffic_interest
}

# Build OpenAI function signatures dynamically
tools_definition = []
for name, fn in tools_available.items():
    tools_definition.append({
        "type": "function",
        "function": {
            "name": name,
            "description": fn.__doc__ or "",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "symbol": {"type": "string"},
                    "cik": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}}
                },
                "required": []
            }
        }
    })

# tools_index_snippet.py
"""
Register free tools (updated function names from financial_tool.py).
Drop this snippet into your main.py or import it to build the tools_available dict.
"""

import google_trends_tool
import financial_tool
import sec_tool
import news_tool
import reddit_tool
import traffic_proxy_tool
import google_search_tool  # optional, if you still use Custom Search

tools_available = {
    # Financial: upgraded Yahoo functions
    "get_yahoo_full_summary": financial_tool.get_yahoo_full_summary,
    "get_yahoo_historical": financial_tool.get_yahoo_historical,
    "get_yahoo_statements": financial_tool.get_yahoo_statements,
    "get_yahoo_modules": financial_tool.get_yahoo_modules,

    # SEC
    "company_filings_index": sec_tool.company_filings_index,
    "fetch_filing_text": sec_tool.fetch_filing_text,

    # Trends / interest
    "google_trends_interest": google_trends_tool.get_interest_over_time,

    # News & social
    "google_news_rss": news_tool.google_news_rss,
    "reddit_search_rss": reddit_tool.reddit_search_rss,

    # Traffic proxy (Trends-based)
    "traffic_interest": traffic_proxy_tool.traffic_interest,

    # Optional fallback search
    "search_google": google_search_tool.search_google
}

# Build OpenAI function schema (tools_definition) for use by the model.
tools_definition = []
for name, fn in tools_available.items():
    tools_definition.append({
        "type": "function",
        "function": {
            "name": name,
            "description": (fn.__doc__ or "")[:1000],
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text query / topic"},
                    "symbol": {"type": "string", "description": "Ticker symbol (eg AAPL)"},
                    "cik": {"type": "string", "description": "SEC CIK (zero-padded)"},
                    "keywords": {"type": "array", "items": {"type": "string"}}
                },
                "required": []
            }
        }
    })

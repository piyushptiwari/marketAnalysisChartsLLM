# main.py
"""
Orchestrator - main FastAPI app that:
- Calls Planning Agent (Agent 1) to create a research_plan
- For each task, asks the model to pick a tool (from free-only tools)
  and returns tool results to the Data & Charting Agent (Agent 2)
  which must return structuredData + plotlyChart JSON object.
"""

import os
import re
import json
import asyncio
import traceback
import urllib.parse
from typing import Any, Dict, List, Tuple
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from fastapi.responses import JSONResponse, StreamingResponse
import io, csv

from openai import AsyncAzureOpenAI  # Azure async OpenAI client

import symbol_resolver


# --- Import your prompts helper (unchanged) ---
from system_prompts import (
    PLANNING_AGENT_PROMPT,
    get_data_chart_agent_messages
)

# --- Import free-only tool modules (no scraping/bs4) ---
import financial_tool
import sec_tool
import google_trends_tool
import news_tool
import reddit_tool
import traffic_proxy_tool
import google_search_tool  # optional: still useful if you kept it (uses Custom Search)

load_dotenv()

# --- Azure/OpenAI config ---
client = AsyncAzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-02-01",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

# --- FastAPI ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Register free tools (function references) ---
# --- Register free tools (function references) ---
tools_available = {
    # Yahoo / Financial
    "get_yahoo_full_summary": financial_tool.get_yahoo_full_summary,
    "get_yahoo_historical": financial_tool.get_yahoo_historical,
    "get_yahoo_statements": financial_tool.get_yahoo_statements,
    "get_yahoo_modules": financial_tool.get_yahoo_modules,

    # SEC
    "company_filings_index": sec_tool.company_filings_index,
    "fetch_filing_text": sec_tool.fetch_filing_text,

    # Trends
    "google_trends_interest": google_trends_tool.get_interest_over_time,

    # News & social
    "google_news_rss": news_tool.google_news_rss,
    "reddit_search_rss": reddit_tool.reddit_search_rss,

    # Traffic proxy (Trends-based)
    "traffic_interest": traffic_proxy_tool.traffic_interest,

    # Optional fallback search
    "search_google": google_search_tool.search_google
}


# --- Build tools_definition for the model (OpenAI function schema) ---
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
                    # flexible parameter schema to allow model to pass the right args
                    "query": {"type": "string", "description": "Text query / topic"},
                    "symbol": {"type": "string", "description": "Ticker symbol (eg AAPL)"},
                    "cik": {"type": "string", "description": "SEC CIK (zero-padded)"},
                    "keywords": {"type": "array", "items": {"type": "string"}, "description": "List of keywords"}
                },
                "required": []
            }
        }
    })


# Simple in-memory TTL cache for tool results
TOOL_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = int(os.getenv("TOOL_CACHE_TTL", "300"))  # default 5 minutes
EVIDENCE_STORE: Dict[str, Dict] = {}

_TICKER_RE = re.compile(r"^[A-Z0-9\-\._]{1,12}$")
def _is_valid_ticker_for_yahoo(sym: str) -> bool:
    if not sym or not isinstance(sym, str):
        return False
    s = sym.strip().upper()
    # allow dot-suffix tickers like BRK.B or NSE style with .NS etc.
    return bool(_TICKER_RE.match(s))

def _cache_get(key: str):
    entry = TOOL_CACHE.get(key)
    if not entry:
        return None
    if datetime.now(timezone.utc) > entry["expires_at"]:
        TOOL_CACHE.pop(key, None)
        return None
    return entry["value"]

def _cache_set(key: str, value: Any, ttl_seconds: int = CACHE_TTL_SECONDS):
    TOOL_CACHE[key] = {
        "value": value,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    }

def run_tool_by_name(tool_name: str, args: Dict[str, Any]):
    fn = tools_available.get(tool_name)
    if fn is None:
        return {"error": f"Tool {tool_name} not registered."}

    cache_key = f"{tool_name}::{json.dumps(args, sort_keys=True, default=str)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {"__cached": True, "result": cached}

    try:
        if "symbol" in args and args.get("symbol"):
            res = fn(args.get("symbol"))
        elif "cik" in args and args.get("cik"):
            res = fn(args.get("cik"))
        elif "keywords" in args and args.get("keywords"):
            res = fn(args.get("keywords"))
        elif "query" in args and args.get("query"):
            res = fn(args.get("query"))
        else:
            res = fn()
        _cache_set(cache_key, res)
        return {"__cached": False, "result": res}
    except Exception as e:
        return {"error": f"Tool execution failed: {str(e)}", "traceback": traceback.format_exc()}


# --- Heuristic tool chooser: simple keyword rules so we don't always rely on the model ---
def heuristic_choose_tool(question: str) -> Dict[str, Any]:
    q = question.lower()
    # Financial / numeric indicators
    if any(k in q for k in ["revenue", "profit", "earnings", "market cap", "marketcap", "eps", "balance sheet", "income statement"]):
        tokens = [t.strip(" ,()") for t in q.split() if t.isupper() and len(t) <= 5]
        if tokens:
            # For structured company metrics, call the full summary
            return {"tool": "get_yahoo_full_summary", "args": {"symbol": tokens[0]}}
        # fallback to SEC CIK mention
        if "cik" in q:
            import re
            m = re.search(r"\b(\d{6,10})\b", q)
            if m:
                return {"tool": "company_filings_index", "args": {"cik": m.group(1)}}
        # If no ticker, return trends + yahoo historical by company name as keywords
        return {"tool": "get_yahoo_full_summary", "args": {"keywords": [question]}}

    # Trends / demand / search interest
    if any(k in q for k in ["trend", "search interest", "search volume", "demand", "google trends", "interest over time"]):
        # If user asked for multiple keywords, pass as keywords array (split by comma)
        if "," in question:
            kws = [s.strip() for s in question.split(",")][:5]
            return {"tool": "google_trends_interest", "args": {"keywords": kws}}
        return {"tool": "google_trends_interest", "args": {"keywords": [question]}}

    # Traffic / visitors / market share (use traffic proxy)
    if any(k in q for k in ["traffic", "visitors", "site visits", "monthly visits", "market share", "top pages"]):
        return {"tool": "traffic_interest", "args": {"keywords": [question]}}

    # News / announcements
    if any(k in q for k in ["news", "announce", "press", "acquir", "launch", "investigation", "lawsuit", "report"]):
        return {"tool": "google_news_rss", "args": {"query": question}}

    # Sentiment / social / reviews
    if any(k in q for k in ["sentiment", "reddit", "reviews", "twitter", "mentions", "social", "forum"]):
        return {"tool": "reddit_search_rss", "args": {"query": question}}

    # Default fallback: use news RSS first
    return {"tool": "google_news_rss", "args": {"query": question}}

# --- Agent 2: Process a single task (updated) ---
async def process_task(task: dict) -> dict:
    task_id = task.get("task_id", "UNKNOWN")
    question = task.get("question", "")

    print(f"[Agent 2] Processing {task_id}: {question}")

    try:
        # --- 0) Try LLM-based ticker resolution first (async) ---
        # symbol_resolver.resolve_ticker_llm returns a dict with keys: symbol, exchange, normalized_name, confidence
        resolved = await symbol_resolver.resolve_ticker_llm(question, client, DEPLOYMENT_NAME)
        # debug log
        print(f"[Agent 2] symbol_resolver for '{question}' -> {resolved}")

        ticker_symbol = resolved.get("symbol", "") or ""
        ticker_conf = float(resolved.get("confidence") or 0.0)

        # Use ticker only if resolver is reasonably confident and ticker looks valid
        USE_TICKER_CONFIDENCE = float(os.getenv("SYMBOL_RESOLVER_CONF", "0.5"))
        if ticker_symbol and ticker_conf >= USE_TICKER_CONFIDENCE and _is_valid_ticker_for_yahoo(ticker_symbol):
            # Build a rich set of evidence tool calls for tickers
            tool_calls: List[Tuple[str, Dict]] = [
                ("get_yahoo_full_summary", {"symbol": ticker_symbol}),
                ("get_yahoo_historical", {"symbol": ticker_symbol, "period_days": int(os.getenv("YH_HISTORY_DAYS","365"))}),
                ("google_trends_interest", {"keywords": [resolved.get("normalized_name") or question]}),
                ("google_news_rss", {"query": resolved.get("normalized_name") or question})
            ]
            # attach resolved info to task for provenance
            task["_resolved_ticker"] = {"symbol": ticker_symbol, "confidence": ticker_conf, "exchange": resolved.get("exchange"), "name": resolved.get("normalized_name")}
        else:
            # No solid ticker — fall back to heuristic chooser (company name / trends)
            heuristic_tool_choice = heuristic_choose_tool(question)
            primary_tool = (heuristic_tool_choice["tool"], heuristic_tool_choice.get("args") or {"query": question})
            # Build complementary evidence calls
            tool_calls = [primary_tool]
            if primary_tool[0] in ("google_trends_interest", "traffic_interest"):
                tool_calls.append(("google_news_rss", {"query": question}))
                tool_calls.append(("reddit_search_rss", {"query": question}))
            else:
                tool_calls.append(("google_trends_interest", {"keywords": [question]}))
                tool_calls.append(("google_news_rss", {"query": question}))

        # 1) Run tools in parallel
        enriched = await run_tools_parallel(tool_calls)

        
        # 3) Merge tool results into normalized rows
        merged_rows = merge_tool_results(enriched)
        
        # 4) Store evidence for this task_id
        now_iso = datetime.now(timezone.utc).isoformat()
        EVIDENCE_STORE[task_id] = {
            "task": task,
            "fetched_at": now_iso,
            "tools": enriched,   # enriched has tool, args, result, source, cached
            "merged_rows": merged_rows
        }

        # Build prominent sources: pick top 3 authoritative sources (SEC, Yahoo, Google Trends, News)
        prominent = []
        for r in enriched:
            src = r.get("source", {})
            # Prefer ones with a URL
            if src.get("url"):
                # classify
                name = src.get("name") or r["tool"]
                typ = "news" if r["tool"].startswith("google_news") else ("trends" if "trends" in r["tool"] else "financial")
                prominent.append({"name": name, "url": src["url"], "tool": r["tool"], "type": typ, "cached": r.get("cached", False)})
        # De-dup by url and limit to 5
        seen = set(); pruned=[]
        for p in prominent:
            if p["url"] in seen: continue
            seen.add(p["url"]); pruned.append(p)
        prominent = pruned[:5]

        # pass merged & evidence bundle to charting agent (string)
        tool_results_bundle = {
            "task": task,
            "question": question,
            "tools": enriched,
            "merged_rows_sample": merged_rows[:100],
            "prominent_sources": prominent
        }
        search_results_str = json.dumps(tool_results_bundle, default=str)


        # 5) Call the Data & Charting agent
        chart_gen_messages = get_data_chart_agent_messages(task, search_results_str)
        second_response = await client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=chart_gen_messages,
            response_format={"type": "json_object"}
        )

        chart_and_data_json = json.loads(second_response.choices[0].message.content)

        # 6) Validate & attach sources for UI
        if "structuredData" not in chart_and_data_json or "plotlyChart" not in chart_and_data_json:
            raise ValueError("Charting agent did not return required keys.")
        # Attach the raw enriched tool data and merged rows (for debugging / drilldown)
        chart_and_data_json["sources"] = [r.get("source") or {"name": r["tool"]} for r in enriched]
        chart_and_data_json["tool_raw_results"] = enriched
        chart_and_data_json["merged_rows"] = merged_rows
        chart_and_data_json["__prominent_sources"] = prominent
        chart_and_data_json["__evidence_key"] = task_id
        return chart_and_data_json
        

    except Exception as e:
        print(f"[Agent 2] Error in task {task_id}: {e}")
        print(traceback.format_exc())
        return {
            "structuredData": [],
            "plotlyChart": {"data": [], "layout": {"title": f"Error generating chart for task {task_id}: {str(e)[:120]}"}},
            "sources": [{"tool": "error", "args": {}, "cached": False, "fetched_at": datetime.now(timezone.utc).isoformat()}],
            "merged_rows": []
        }


# --- Run multiple tools in parallel & return list of (tool_name, args, result, source_meta) ---
async def run_tools_parallel(tool_calls: List[Tuple[str, Dict]]) -> List[Dict]:
    """
    tool_calls: list of (tool_name, args_dict)
    Returns: list of dicts: { tool: str, args: dict, result: <py obj>, source: {name,url}, cached: bool }
    """
    loop = asyncio.get_event_loop()
    futures = []
    for tool_name, args in tool_calls:
        # run sync run_tool_by_name in threadpool to avoid blocking
        futures.append(loop.run_in_executor(None, run_tool_by_name, tool_name, args))
    results = await asyncio.gather(*futures)
    enriched = []
    for idx, res in enumerate(results):
        tool_name, args = tool_calls[idx]
        # Determine a best-effort public link for the tool results, to show as "source link":
        source_url = None
        if tool_name == "get_yahoo_full_summary" and args.get("symbol"):
            source_url = f"https://finance.yahoo.com/quote/{urllib.parse.quote(args['symbol'])}"
        elif tool_name == "company_filings_index" and args.get("cik"):
            cik = str(args["cik"]).zfill(10)
            source_url = f"https://www.sec.gov/ix?doc=/Archives/edgar/data/{int(cik)}/{cik}-index.htm"
        elif tool_name == "google_trends_interest" and args.get("keywords"):
            # google trends web search link (single-keyword fallback)
            k0 = args["keywords"][0] if isinstance(args["keywords"], list) and args["keywords"] else args.get("keywords")
            source_url = f"https://trends.google.com/trends/explore?q={urllib.parse.quote(k0)}"
        elif tool_name in ("google_news_rss", "reddit_search_rss"):
            # we can't provide single canonical URL, provide search URL
            q = args.get("query") or (args.get("keywords") and ",".join(args.get("keywords")))
            if q:
                if tool_name == "google_news_rss":
                    source_url = f"https://news.google.com/search?q={urllib.parse.quote(q)}"
                else:
                    source_url = f"https://www.reddit.com/search?q={urllib.parse.quote(q)}"
        elif tool_name == "traffic_interest" and args.get("keywords"):
            k0 = args["keywords"][0]
            source_url = f"https://trends.google.com/trends/explore?q={urllib.parse.quote(k0)}"
        else:
            source_url = None

        cached = False
        if isinstance(res, dict) and "__cached" in res:
            cached = bool(res["__cached"])
            result_obj = res.get("result")
        else:
            result_obj = res

        enriched.append({
            "tool": tool_name,
            "args": args,
            "result": result_obj,
            "source": {"name": tool_name, "url": source_url} if source_url else {"name": tool_name},
            "cached": cached
        })
    return enriched

# --- Merge & normalize multiple tool results into a single list of rows
def merge_tool_results(enriched_tool_results: List[Dict]) -> List[dict]:
    """
    Best-effort merging:
      - If any tool returns obvious tabular data (list/dict), flatten them to rows.
      - If only snippets, return parsed snippet rows with 'snippet' + source.
    Returns: list of rows like {col1: val, col2: val, sources: [{name,url}], confidence: 1.0}
    """
    merged_rows = []
    for res in enriched_tool_results:
        tool = res["tool"]
        src = res.get("source", {})
        data = res.get("result")

        # If data is a dict and contains common fields (e.g., quoteSummary), extract numeric pieces
        if isinstance(data, dict) and ("quoteSummary" in data or "price" in data or "financialData" in data):
            # Extract a few common numeric fields when present
            # This is conservative — Charting Agent will be told explicit sources and must prefer these numbers
            # Example: yahoo v10 response
            try:
                # try price
                if "quoteSummary" in data:
                    q = data.get("quoteSummary", {})
                    # some endpoints return nested structure
                    modules = q.get("result", [{}])[0] if q.get("result") else q.get("result")
                    if isinstance(modules, dict):
                        # look into modules for numeric values
                        row = {"symbol": None}
                        # price module
                        price = modules.get("price")
                        if price:
                            row["symbol"] = price.get("symbol")
                            for k in ("regularMarketPrice", "marketCap", "regularMarketVolume"):
                                if price.get(k) and isinstance(price.get(k), (int, float, dict)):
                                    # If it's a dict from Yahoo, try value field
                                    val = price.get(k)
                                    if isinstance(val, dict):
                                        v = val.get("raw") or val.get("fmt") or None
                                    else:
                                        v = val
                                    row[k] = v
                        # financialData revenue/ebitda, if available
                        fd = modules.get("financialData")
                        if fd and isinstance(fd, dict):
                            for fk in ("totalRevenue", "ebitda", "grossProfits"):
                                if fd.get(fk):
                                    val = fd[fk]
                                    row[fk] = val.get("raw") if isinstance(val, dict) else val
                        # attach sources
                        row["sources"] = [src]
                        row["confidence"] = 0.95
                        merged_rows.append(row)
                        continue
            except Exception:
                pass

        # If the tool returned a list of items (news / reddit)
        if isinstance(data, list):
            for item in data:
                row = {}
                if isinstance(item, dict):
                    # prefer title, link, published, summary
                    for k in ("title", "link", "published", "summary"):
                        if item.get(k):
                            row[k] = item.get(k)
                    row["sources"] = [item.get("link") and {"name": tool, "url": item.get("link")} or src]
                    row["confidence"] = 0.6
                else:
                    row = {"snippet": str(item), "sources": [src], "confidence": 0.4}
                merged_rows.append(row)
            continue

        # Fallback: treat result as a snippet or dict — convert to string row
        merged_rows.append({
            "snippet": str(data)[:2000],
            "sources": [src],
            "confidence": 0.3
        })
    return merged_rows


# --- Main orchestrator endpoint ---
@app.get("/api/get-dashboard-data")
async def get_dashboard_data(topic: str = Query("Global electric vehicle (EV) market analysis")):
    print(f"[Orchestrator] New topic: {topic}")

    try:
        # 1) Ask Agent 1 (Planning) to create the research_plan JSON
        print("[Orchestrator] Calling Planning Agent...")
        planning_response = await client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": PLANNING_AGENT_PROMPT},
                {"role": "user", "content": topic}
            ],
            response_format={"type": "json_object"}
        )

        plan_json = json.loads(planning_response.choices[0].message.content)
        research_plan = plan_json.get("research_plan", [])
        if not research_plan:
            raise ValueError("Planning agent returned an empty research plan.")

        print(f"[Orchestrator] Research plan with {len(research_plan)} tasks received.")

        # 2) Process each task in parallel
        task_coros = [process_task(task) for task in research_plan]
        print(f"[Orchestrator] Launching {len(task_coros)} tasks...")
        results = await asyncio.gather(*task_coros)

        print("[Orchestrator] All tasks complete, returning dashboard.")
        return {"charts": results}

    except Exception as e:
        print(f"[Orchestrator] Orchestration failed: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Failed to generate dashboard: {str(e)}")

# --- Deep Dive endpoint to collect data for a list of competitors (domain names or company names)
@app.post("/api/deep-dive")
async def deep_dive(payload: dict):
    """
    POST payload:
    {
      "topic": "Electric vehicles",
      "competitors": ["Tesla", "BYD", "Volkswagen"],
      "tasks": [ optional list of task dicts to run per competitor ]
    }
    """
    try:
        topic = payload.get("topic", "")
        competitors = payload.get("competitors", [])
        if not competitors:
            raise HTTPException(status_code=400, detail="competitors list required")

        # Build a set of tool calls per competitor: yahoo summary (if ticker-like), google trends for brand, news and reddit
        tool_calls = []
        for comp in competitors:
                        # Add trends/news/reddit for name
            tool_calls.append(("google_trends_interest", {"keywords": [comp]}))
            tool_calls.append(("google_news_rss", {"query": comp}))
            tool_calls.append(("reddit_search_rss", {"query": comp}))

            # Attempt to resolve ticker using LLM (synchronous call via run_in_executor is possible but here we call resolver directly)
            try:
                resolved = await symbol_resolver.resolve_ticker_llm(comp, client, DEPLOYMENT_NAME)
                sym = resolved.get("symbol","")
                conf = float(resolved.get("confidence") or 0.0)
                if sym and conf >= float(os.getenv("SYMBOL_RESOLVER_CONF", "0.5")) and _is_valid_ticker_for_yahoo(sym):
                    tool_calls.append(("get_yahoo_full_summary", {"symbol": sym}))
                    tool_calls.append(("get_yahoo_historical", {"symbol": sym, "period_days": int(os.getenv('YH_HISTORY_DAYS','365'))}))
            except Exception as _e:
                # ignore resolver failures; we still have trends/news
                print(f"[DeepDive] resolver failed for {comp}: {_e}")

        # Run all tools in parallel
        enriched = await run_tools_parallel(tool_calls)
        # Merge results into one dataset
        merged = merge_tool_results(enriched)
        return {"competitors": competitors, "tool_calls": tool_calls, "enriched": enriched, "merged": merged}
    except HTTPException:
        raise
    except Exception as e:
        print("Deep dive error:", e)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/evidence/{task_id}")
async def get_evidence(task_id: str):
    ev = EVIDENCE_STORE.get(task_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return JSONResponse(content=ev)

@app.get("/api/evidence/{task_id}/csv")
async def get_evidence_csv(task_id: str):
    ev = EVIDENCE_STORE.get(task_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Evidence not found")
    merged = ev.get("merged_rows", [])
    if not merged:
        raise HTTPException(status_code=404, detail="No merged data available")
    # Create CSV from merged rows (keys union)
    keys = set()
    for r in merged:
        keys.update(r.keys())
    keys = list(keys)
    bio = io.StringIO()
    writer = csv.DictWriter(bio, fieldnames=keys)
    writer.writeheader()
    for r in merged:
        # flatten sources into single string
        rr = r.copy()
        if "sources" in rr:
            try:
                rr["sources"] = "; ".join([ (s.get("url") or s.get("name") or str(s)) for s in rr["sources"] ])
            except Exception:
                rr["sources"] = str(rr["sources"])
        writer.writerow(rr)
    bio.seek(0)
    return StreamingResponse(io.BytesIO(bio.getvalue().encode('utf-8')), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={task_id}_evidence.csv"})


if __name__ == "__main__":
    import uvicorn
    print("Starting backend server on http://0.0.0.0:8001")
    uvicorn.run(app="main:app", host="0.0.0.0", port=8001, reload=True)

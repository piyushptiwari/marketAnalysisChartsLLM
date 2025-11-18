# main.py
"""
Orchestrator - main FastAPI app that:
- Calls Planning Agent (Agent 1) to create a research_plan
- For each task, asks the model to pick a tool (from free-only tools)
  and returns tool results to the Data & Charting Agent (Agent 2)
  which must return structuredData + plotlyChart JSON object.
"""

import os
import json
import asyncio
import traceback
from typing import Any, Dict
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from openai import AsyncAzureOpenAI  # Azure async OpenAI client

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
tools_available = {
    "get_yahoo_summary": financial_tool.get_yahoo_summary,
    "get_stock_price": financial_tool.get_stock_price,
    "get_sec_companyfacts": financial_tool.get_sec_companyfacts,
    "company_filings_index": sec_tool.company_filings_index,
    "fetch_filing_text": sec_tool.fetch_filing_text,
    "google_trends_interest": google_trends_tool.get_interest_over_time,
    "google_trends_related": google_trends_tool.get_related_queries,
    "google_news_rss": news_tool.google_news_rss,
    "reddit_search_rss": reddit_tool.reddit_search_rss,
    "traffic_interest": traffic_proxy_tool.traffic_interest,
    "search_google": google_search_tool.search_google  # optional if you still want Custom Search fallback
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
        # If ticker present like (AAPL) or TSLA or symbol: find a token that looks like ticker
        tokens = [t.strip(" ,()") for t in q.split() if t.isupper() and len(t) <= 5]
        if tokens:
            return {"tool": "get_yahoo_summary", "args": {"symbol": tokens[0]}}
        # fallback to SEC CIK mention
        if "cik" in q:
            # try to extract numbers
            import re
            m = re.search(r"\b(\d{6,10})\b", q)
            if m:
                return {"tool": "get_sec_companyfacts", "args": {"cik": m.group(1)}}
        return {"tool": "get_yahoo_summary", "args": {"symbol": "AAPL"}}

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
        # 1) Heuristic choose tool
        heuristic = heuristic_choose_tool(question)
        tool_name = heuristic["tool"]
        tool_args = heuristic.get("args", {})

        # 2) Execute the chosen tool
        tool_execution = run_tool_by_name(tool_name, tool_args)
        tool_cached_flag = tool_execution.get("__cached", False)
        tool_result = tool_execution.get("result") if "__cached" in tool_execution else tool_execution

        # 3) Build sources metadata
        now_iso = datetime.now(timezone.utc).isoformat()
        sources = [{
            "tool": tool_name,
            "args": tool_args,
            "cached": bool(tool_cached_flag),
            "fetched_at": now_iso
        }]

        # 4) If heuristic produced no useful numeric result (or returned error), allow model to choose a tool
        if isinstance(tool_result, dict) and (tool_result.get("error") or (not tool_result and tool_name == "google_news_rss")):
            print(f"[Agent 2] Heuristic result poor or error; asking model to choose a tool for task {task_id}.")
            selection_messages = [
                {"role": "system", "content": "You are a research assistant. Choose the best free tool to fetch real data for the question. Respond by invoking the tool."},
                {"role": "user", "content": f"Task ID: {task_id}\nQuestion: {question}\nAvailable tools: {list(tools_available.keys())}\nReturn a tool function call with args."}
            ]
            first_response = await client.chat.completions.create(
                model=DEPLOYMENT_NAME,
                messages=selection_messages,
                tools=tools_definition
            )
            try:
                tool_call = first_response.choices[0].message.tool_calls[0]
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                tool_execution = run_tool_by_name(tool_name, tool_args)
                tool_cached_flag = tool_execution.get("__cached", False)
                tool_result = tool_execution.get("result") if "__cached" in tool_execution else tool_execution
                sources.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "cached": bool(tool_cached_flag),
                    "fetched_at": datetime.now(timezone.utc).isoformat()
                })
            except Exception:
                # keep original tool_result and continue
                pass

        # 5) Serialize tool_result to string for the charting agent
        try:
            search_results_str = json.dumps(tool_result, default=str)
        except Exception:
            search_results_str = json.dumps({"error": "Could not serialize tool results."})

        # 6) Call the Data & Charting agent
        chart_gen_messages = get_data_chart_agent_messages(task, search_results_str)
        second_response = await client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            messages=chart_gen_messages,
            response_format={"type": "json_object"}
        )
        chart_and_data_json = json.loads(second_response.choices[0].message.content)

        # 7) VALIDATION & attach sources
        if "structuredData" not in chart_and_data_json or "plotlyChart" not in chart_and_data_json:
            raise ValueError("Charting agent did not return required keys.")
        chart_and_data_json["sources"] = sources
        chart_and_data_json["tool_raw_result"] = tool_result  # optional for debugging / deeper inspection
        return chart_and_data_json

    except Exception as e:
        print(f"[Agent 2] Error in task {task_id}: {e}")
        print(traceback.format_exc())
        return {
            "structuredData": [],
            "plotlyChart": {"data": [], "layout": {"title": f"Error generating chart for task {task_id}: {str(e)[:120]}" }},
            "sources": [{"tool": "error", "args": {}, "cached": False, "fetched_at": datetime.now(timezone.utc).isoformat()}]
        }

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


if __name__ == "__main__":
    import uvicorn
    print("Starting backend server on http://0.0.0.0:8001")
    uvicorn.run(app="main:app", host="0.0.0.0", port=8001, reload=True)

# symbol_resolver.py
"""
Resolve company/brand name -> ticker symbol using an LLM (Azure OpenAI).
Provides:
- async resolve_ticker_llm(name, client, deployment_name, prefer_exchange=None)
  returns: { "symbol": "TSLA", "exchange": "NASDAQ", "normalized_name": "Tesla, Inc.", "confidence": 0.92, "sources": [...], "raw": {...} }
Caching: in-memory TTL cache to avoid repeated LLM calls.
"""

import re
import json
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

# Simple in-memory cache: { key_lower_name: {value:..., expires_at: datetime} }
_RESOLVER_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SECONDS = 3600  # 1 hour cache for lookup results

# Strict ticker regex (common pattern: letters, optionally .EX for exchange suffix)
_TICKER_RE = re.compile(r"^[A-Z0-9\-\.]{1,10}$")

def _cache_get(name: str) -> Optional[Dict[str, Any]]:
    k = name.strip().lower()
    entry = _RESOLVER_CACHE.get(k)
    if not entry:
        return None
    if datetime.now(timezone.utc) > entry["expires_at"]:
        _RESOLVER_CACHE.pop(k, None)
        return None
    return entry["value"]

def _cache_set(name: str, value: Dict[str, Any], ttl: int = CACHE_TTL_SECONDS):
    k = name.strip().lower()
    _RESOLVER_CACHE[k] = {"value": value, "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl)}

def _is_valid_ticker(sym: str) -> bool:
    if not sym or not isinstance(sym, str):
        return False
    return bool(_TICKER_RE.match(sym.strip().upper()))

# Template prompt: ask the model to respond ONLY in a compact JSON format
_RESOLVER_SYSTEM_PROMPT = """
You are a precise market-data assistant. Given a company name, return a single JSON object with these keys:
- symbol: the best matching stock ticker (short uppercase string) or empty string if none
- exchange: best-guess exchange (e.g., NASDAQ, NYSE, NSE, BSE, LSE) or empty string
- normalized_name: canonical company name (short)
- confidence: float between 0 and 1 representing your confidence
- reason: one concise sentence stating why this ticker was chosen (include any ambiguity)
- sources: an array of 0..3 short references the model used to decide (e.g., 'NASDAQ list', 'Yahoo Finance', 'company website')
Return ONLY the JSON object, no explanation or extra text.
"""

# Example JSON validator/parsing helper
def _parse_llm_response_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Try to extract the first JSON object contained in the text.
    """
    try:
        # If the model returned raw JSON, parse directly
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        # fallback: find first {...} block
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and start < end:
            try:
                obj = json.loads(text[start:end+1])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                return None
    return None

# Async resolver using an async Azure OpenAI client (same client used in main.py)
async def resolve_ticker_llm(name: str, client, deployment_name: str, prefer_exchange: Optional[str] = None, max_tokens: int = 300) -> Dict[str, Any]:
    """
    name: company/brand name or query (e.g., "Tesla", "Reliance Industries", "Infosys")
    client: AsyncAzureOpenAI client instance (from your main.py)
    deployment_name: Azure deployment name to use for chat completions
    prefer_exchange: optional hint (e.g., "NSE", "NASDAQ") to bias the model
    Returns a structured dict; if no valid ticker found, symbol will be "" and confidence low.
    """
    if not name or not client or not deployment_name:
        return {"symbol": "", "exchange": "", "normalized_name": name, "confidence": 0.0, "reason": "missing parameters", "sources": [], "raw": {}}

    cached = _cache_get(name)
    if cached:
        cached_copy = dict(cached)
        cached_copy["_from_cache"] = True
        return cached_copy

    # Build the user prompt including optional exchange hint
    user_content = f"""
Company or brand: "{name}"

If you can map this to a single publicly traded stock ticker, return the JSON object described in the system prompt.
If multiple plausible tickers exist, choose the primary public company that most people mean when using this brand name.
If you are unsure, set symbol to an empty string and confidence to 0.0.
Prefer exchanges: {prefer_exchange if prefer_exchange else "none"}.
"""

    try:
        response = await client.chat.completions.create(
            model=deployment_name,
            messages=[
                {"role": "system", "content": _RESOLVER_SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            max_tokens=max_tokens,
            temperature=0.0
        )
        raw_text = response.choices[0].message.content
        parsed = _parse_llm_response_text(raw_text)
        if not parsed:
            parsed = {"symbol": "", "exchange": "", "normalized_name": name, "confidence": 0.0, "reason": "failed_parse", "sources": [], "raw": {"raw_text": raw_text}}
        # Normalize keys and types
        symbol = (parsed.get("symbol") or "").strip().upper()
        exchange = (parsed.get("exchange") or "").strip()
        normalized_name = parsed.get("normalized_name") or name
        try:
            confidence = float(parsed.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        reason = parsed.get("reason") or ""
        sources = parsed.get("sources") or []

        # Validate ticker format; if invalid, clear symbol and reduce confidence
        if symbol and not _is_valid_ticker(symbol):
            # The model returned something that doesn't look like a ticker
            reason = (reason + " | invalid ticker format").strip()
            symbol = ""
            confidence = min(confidence, 0.35)

        out = {
            "symbol": symbol,
            "exchange": exchange,
            "normalized_name": normalized_name,
            "confidence": confidence,
            "reason": reason,
            "sources": sources,
            "raw": parsed
        }

        _cache_set(name, out)
        return out

    except Exception as e:
        # Return graceful failure
        out = {"symbol": "", "exchange": "", "normalized_name": name, "confidence": 0.0, "reason": f"llm_error: {str(e)}", "sources": [], "raw": {}}
        _cache_set(name, out)
        return out

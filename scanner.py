import json
import os
import re
import time
from typing import Optional

import groq
from dotenv import load_dotenv

load_dotenv()

MODEL = "llama-3.3-70b-versatile"

_client: Optional[groq.Groq] = None


def _get_client() -> groq.Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY is not set")
        _client = groq.Groq(api_key=api_key)
    return _client


CATEGORIES = [
    ("auto_renewal",           "Auto-Renewal"),
    ("price_escalation",       "Price Increases"),
    ("data_ownership",         "Data Ownership"),
    ("termination_rights",     "Termination Rights"),
    ("liability_cap",          "Liability Cap"),
    ("data_portability",       "Data Portability & Exit"),
    ("unilateral_modification","Unilateral Changes"),
    ("governing_law",          "Governing Law"),
    ("sla_remedies",           "SLA & Remedies"),
]

_CATEGORY_LIST = " | ".join(c for c, _ in CATEGORIES)

SYSTEM_PROMPT = f"""You are a senior SaaS procurement lawyer analysing contracts on behalf of the buyer.
Extract risk information for exactly 9 clause categories and return ONLY a valid JSON object — no preamble, no markdown fences, no text outside the JSON.

JSON schema:
{{
  "vendor_name": string or null,
  "overall_risk_score": integer 0-100 (higher = riskier for the buyer),
  "overall_grade": "A" or "B" or "C" or "D" or "F",
  "executive_summary": "2-3 plain-English sentences for a procurement manager",
  "findings": [ exactly 9 objects, one per category in order ],
  "key_dates": [ {{"label": string, "value": string}} ],
  "favorable_terms": [ string ]
}}

Each finding object:
{{
  "category": one of: {_CATEGORY_LIST},
  "display_name": string,
  "severity": "critical" or "high" or "medium" or "low" or "ok" or "not_found",
  "headline": "10 words or fewer — punchy, e.g. 30-day cancellation window",
  "clause_excerpt": "verbatim quote under 250 chars, or null if not_found",
  "plain_english": "what this means for the buyer in 1-2 sentences",
  "negotiation_tip": "one sentence on what to push back on, or null if not_found or ok"
}}

Severity guide:
- critical: actively harmful to buyer (auto-renews with under 30-day notice, vendor can raise price any amount without cap, no data return on exit)
- high: buyer-unfavorable but common in market (liability capped at 3 months fees, 60-day notice window, broad IP assignment)
- medium: standard market terms with moderate buyer risk
- low: buyer-favorable or well-balanced
- ok: clause explicitly protects the buyer
- not_found: this clause type does not appear in the provided text

Grading guide (based on critical+high count):
- A: 0 critical, 0-1 high
- B: 0 critical, 2-3 high
- C: 1 critical OR 4+ high
- D: 2 critical
- F: 3+ critical

Always output all 9 findings in the order listed. Never skip a category."""


def _extract_json(raw: str) -> dict:
    def _ensure_dict(obj):
        if not isinstance(obj, dict):
            raise ValueError(f"Expected JSON object, got {type(obj).__name__}")
        return obj

    try:
        return _ensure_dict(json.loads(raw))
    except (json.JSONDecodeError, ValueError):
        pass

    cleaned = re.sub(r"```(?:json)?", "", raw).strip(" \n`")
    try:
        return _ensure_dict(json.loads(cleaned))
    except (json.JSONDecodeError, ValueError):
        pass

    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    # Try finding the first valid JSON object via brace counting
    depth, start = 0, -1
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    start = -1

    raise ValueError("Could not extract JSON from LLM response")


_MAX_TEXT_CHARS = 25_000  # ~6,250 tokens, leaves headroom for prompt + output


def _call_with_retry(messages: list, max_retries: int = 3) -> str:
    client = _get_client()
    delay = 1
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.1,
                max_tokens=2048,
            )
            return resp.choices[0].message.content or ""
        except groq.RateLimitError as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
        except groq.APIStatusError as e:
            if e.status_code == 413:
                raise RuntimeError(
                    "Contract text is too long for analysis. "
                    "Try pasting a shorter excerpt (key sections only)."
                ) from e
            raise
    raise last_err


def scan(text: str, focus: Optional[str] = None) -> dict:
    text = text[:_MAX_TEXT_CHARS]
    user_content = f"Analyze the following contract text:\n\n{text}"
    if focus and focus.strip():
        user_content += f"\n\nBuyer's priority focus: {focus.strip()} — weight your severity ratings and executive summary toward these concerns."

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_content},
    ]

    raw = _call_with_retry(messages)

    try:
        result = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Analysis failed — AI response could not be parsed: {e}") from e

    # Normalise: fill in any keys the LLM omitted
    result.setdefault("vendor_name", None)
    result.setdefault("overall_risk_score", 0)
    result.setdefault("overall_grade", "F")
    result.setdefault("executive_summary", "")
    result.setdefault("findings", [])
    result.setdefault("key_dates", [])
    result.setdefault("favorable_terms", [])

    return result

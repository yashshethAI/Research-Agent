from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.app.agents.state import ResearchState
from backend.app.llm.factory import llm_factory

logger = logging.getLogger(__name__)


def _extract_json_from_text(text: str) -> dict[str, Any]:
    """Helper to extract JSON object from LLM response text."""
    try:
        # Check for ```json ... ``` blocks
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        # Direct json loads
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
    except Exception as e:
        logger.warning(f"Failed to parse JSON from LLM output: {e}")
    return {}


def _extract_facts_heuristically(query: str) -> dict[str, Any]:
    """Fast, deterministic extraction of GST topics, provisions, and factual context."""
    topics: list[str] = []

    # Detect provisions
    sections = re.findall(r"(?:Section|Sec\.?)\s*(\d+[A-Za-z]?(?:\([0-9a-zA-Z]+\))*)", query, re.IGNORECASE)
    rules = re.findall(r"(?:Rule|R\.)\s*(\d+[A-Za-z]?(?:\([0-9a-zA-Z]+\))*)", query, re.IGNORECASE)

    for s in sections:
        topics.append(f"Section {s}")
    for r in rules:
        topics.append(f"Rule {r}")

    q_lower = query.lower()
    if "itc" in q_lower or "input tax credit" in q_lower:
        topics.append("Input Tax Credit (ITC)")
    if "rcm" in q_lower or "reverse charge" in q_lower:
        topics.append("Reverse Charge Mechanism (RCM)")
    if "place of supply" in q_lower or "cross-border" in q_lower or "export" in q_lower or "import" in q_lower:
        topics.append("Place of Supply (IGST)")
    if "audit" in q_lower or "scn" in q_lower or "show cause" in q_lower or "73" in q_lower or "74" in q_lower:
        topics.append("Demands, Audit & Penalties")
    if "remuneration" in q_lower or "director" in q_lower:
        topics.append("Director Remuneration & Levy")
    if "invoice" in q_lower or "e-way" in q_lower or "eway" in q_lower:
        topics.append("Invoicing & E-Way Bill Compliance")

    if not topics:
        topics = ["General GST Advisory"]

    # Detect FY (default to active Indian FY in IST if not explicitly stated)
    from datetime import datetime, timedelta, timezone

    ist_tz = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist_tz)
    default_fy = f"FY {now.year}-{str(now.year + 1)[-2:]}" if now.month >= 4 else f"FY {now.year - 1}-{str(now.year)[-2:]}"

    fy_match = re.search(r"\b(FY\s*)?20\d{2}[-–/]\d{2,4}\b", query, re.IGNORECASE)
    fy = fy_match.group(0) if fy_match else default_fy

    return {
        "gst_topics": list(dict.fromkeys(topics)),
        "financial_year": fy,
        "tax_period": "Current Statutory Period",
        "jurisdiction": "Central / All India (CGST/IGST)",
        "taxpayer_type": "Regular Registered Taxable Person",
        "nature_of_supply": "Standard Taxable Supply",
        "material_facts": [query],
    }


async def query_understanding_node(state: ResearchState) -> dict:
    """Node 2: Fast, deterministic extraction of GST topics, statutory provisions, and tax facts."""
    query = state.query

    # 1. Check if LLM endpoint is configured
    if not llm_factory.is_configured():
        guidance = (
            "### ⚖️ GST PRACTICE COPILOT — INFERENCE SETUP REQUIRED\n\n"
            "The legal research agent is running in local-first mode, but no active LLM endpoint was detected.\n\n"
            "To activate statutory reasoning and memorandum synthesis:\n"
            "1. Open your local `.env` file in the project root.\n"
            "2. Configure an OpenAI-compatible endpoint (Ollama, vLLM, DeepInfra, etc.):\n"
            "   ```bash\n"
            "   # For Local Ollama:\n"
            "   LLM_BASE_URL=http://127.0.0.1:11434/v1\n"
            "   LLM_MODEL=qwen2.5:14b\n"
            "   LLM_API_KEY=none\n\n"
            "   # For DeepInfra / Remote Serverless:\n"
            "   LLM_BASE_URL=https://api.deepinfra.com/v1\n"
            "   LLM_API_KEY=your_deepinfra_key\n"
            "   LLM_MODEL=Qwen/Qwen2.5-14B-Instruct\n"
            "   ```\n"
            "3. Restart the backend service or send a new query once your model server is running.\n\n"
            "> **Note for CA Firms:** No client data or queries leave your local environment when using a local Ollama or vLLM instance."
        )
        return {
            "current_step": "query_understanding",
            "llm_unconfigured_guidance": guidance,
            "final_report": guidance,
        }

    # Fast heuristic extraction for instant sub-second statutory lookup planning
    extracted_facts = _extract_facts_heuristically(query)
    assumptions = [
        "Taxpayer assumed to be a regular registered taxable person under Section 22/24 of the CGST Act, 2017.",
        "Supplies are assumed to be made in the course or furtherance of business under active GST provisions.",
    ]

    return {
        "current_step": "query_understanding",
        "extracted_facts": extracted_facts,
        "assumptions": assumptions,
        "missing_facts": [],
        "needs_clarification": False,
        "clarification_prompt": "",
    }

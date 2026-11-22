from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.agents.prompts import (
    GST_RESEARCHER_SYSTEM_PROMPT,
    QUERY_UNDERSTANDING_PROMPT,
)
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


async def query_understanding_node(state: ResearchState) -> dict:
    """Node 2: Classifies multi-topic GST question, tax period, transaction date, and role."""
    query = state.query

    # If LLM is not configured, prepare guidance for unconfigured mode
    if not llm_factory.is_configured():
        logger.warning("LLM endpoint not configured. Generating CA-styled setup guidance.")
        guidance = (
            "### ⚖️ GST PRACTICE COPILOT — RUNTIME INFERENCE SETUP REQUIRED\n\n"
            "Welcome to **GST Practice Copilot (India)**. The application runtime has initialized successfully in local-first mode.\n\n"
            "To perform live statutory GST research, date-aware legal analysis, and official CBIC/GSTN citation verification, "
            "an **OpenAI-compatible inference endpoint** (such as **Ollama**, **vLLM**, **llama.cpp**, or a private cloud endpoint) must be connected.\n\n"
            "#### How to Configure Your Local LLM Endpoint:\n"
            "1. Open your project `.env` file in the root workspace.\n"
            "2. Configure the following parameters:\n"
            "   ```env\n"
            "   # For Ollama running locally:\n"
            "   LLM_BASE_URL=http://localhost:11434/v1\n"
            "   LLM_MODEL=qwen2.5:14b  # or llama3.1:8b / mistral\n"
            "   LLM_API_KEY=none\n\n"
            "   # For vLLM server:\n"
            "   LLM_BASE_URL=http://localhost:8000/v1\n"
            "   LLM_MODEL=your_served_model_name\n"
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

    # Format context from previous messages
    context_turns = []
    for msg in state.messages[-4:]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        context_turns.append(f"{role.capitalize()}: {content}")
    context_str = "\n".join(context_turns) if context_turns else "None (New Conversation)"

    prompt = QUERY_UNDERSTANDING_PROMPT.format(query=query, context=context_str)

    try:
        llm = llm_factory.get_chat_model()
        response = await llm.ainvoke([
            SystemMessage(content=GST_RESEARCHER_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        content_text = response.content if isinstance(response.content, str) else str(response.content)
        parsed = _extract_json_from_text(content_text)

        gst_topics = parsed.get("gst_topics", ["General GST Compliance"])
        fy = parsed.get("financial_year", "Not Specified")
        tax_period = parsed.get("tax_period", "Not Specified")
        txn_date = parsed.get("transaction_date", "Not Specified")
        jurisdiction = parsed.get("jurisdiction", "Central / All India")
        taxpayer_type = parsed.get("taxpayer_type", "Regular Taxable Person")
        nature_of_supply = parsed.get("nature_of_supply", "Standard Taxable Supply")
        material_facts = parsed.get("material_facts", [query])
        missing_critical_facts = parsed.get("missing_critical_facts", [])
        assumptions = parsed.get("assumptions", [])
        needs_clarification = bool(parsed.get("needs_clarification", False))
        clarification_question = parsed.get("clarification_question", "")

        extracted_facts = {
            "gst_topics": gst_topics,
            "financial_year": fy,
            "tax_period": tax_period,
            "transaction_date": txn_date,
            "jurisdiction": jurisdiction,
            "taxpayer_type": taxpayer_type,
            "nature_of_supply": nature_of_supply,
            "material_facts": material_facts,
        }

        return {
            "current_step": "query_understanding",
            "extracted_facts": extracted_facts,
            "assumptions": assumptions,
            "missing_facts": missing_critical_facts,
            "needs_clarification": needs_clarification,
            "clarification_prompt": clarification_question,
        }
    except Exception as e:
        logger.error(f"Error in query_understanding_node: {e}")
        # Rule-based fallback
        fallback_facts = {
            "gst_topics": ["Goods and Services Tax"],
            "financial_year": "Current Period",
            "jurisdiction": "Central",
            "taxpayer_type": "Regular",
            "material_facts": [query],
        }
        return {
            "current_step": "query_understanding",
            "extracted_facts": fallback_facts,
            "assumptions": ["Proceeding with standard provisions under CGST Act, 2017."],
            "needs_clarification": False,
        }

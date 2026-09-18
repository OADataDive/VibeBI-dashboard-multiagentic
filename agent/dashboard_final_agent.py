from __future__ import annotations

import json

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)

from llm import llm
from utils import extract_json


# ============================================================
# AGENT 7 — DASHBOARD FINAL AGENT
# ============================================================


DASHBOARD_FINAL_PROMPT = """
You are a Dashboard Final Agent.

Summarize the completed dashboard execution.

You receive:
- requested KPI count
- requested chart count
- successful KPI count
- successful chart count
- remaining errors

Rules:
- Do not change SQL.
- Do not create or modify charts.
- Do not invent results.
- Do not expose chain-of-thought.

Return JSON only:

{
  "status": "success|partial|failed",
  "requested_kpis": 0,
  "successful_kpis": 0,
  "requested_charts": 0,
  "successful_charts": 0,
  "remaining_failures": [],
  "message": "short summary"
}
"""


# ============================================================
# DASHBOARD FINAL TOOLS
#
# None. Final Agent summarizes only.
# ============================================================


def dashboard_final_agent_node(
    state,
):
    results = state.get(
        "dashboard_results",
        {},
    )

    successful_kpis = len(
        results.get(
            "kpis",
            [],
        )
    )

    successful_charts = len(
        results.get(
            "charts",
            [],
        )
    )

    constraints = state[
        "count_constraints"
    ]

    input_message = f"""
REQUESTED KPIS:

{constraints.get("kpis", 0)}


SUCCESSFUL KPIS:

{successful_kpis}


REQUESTED CHARTS:

{constraints.get("charts", 0)}


SUCCESSFUL CHARTS:

{successful_charts}


REMAINING ERRORS:

{json.dumps(
    state.get(
        "dashboard_errors",
        [],
    ),
    indent=2,
    default=str,
)}
"""

    response = llm.invoke(
        [
            SystemMessage(
                content=
                    DASHBOARD_FINAL_PROMPT
            ),
            HumanMessage(
                content=input_message
            ),
        ]
    )

    return {
        "messages": [
            response
        ],
        "dashboard_final":
            extract_json(
                response.content
            ),
    }

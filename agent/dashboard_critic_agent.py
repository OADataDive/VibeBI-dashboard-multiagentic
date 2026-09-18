from __future__ import annotations

import json

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)

from llm import llm
from utils import extract_json


# ============================================================
# AGENT 6 — DASHBOARD CRITIC AGENT
# ============================================================

DASHBOARD_CRITIC_PROMPT = """
You are a Dashboard Critic Agent.

A dashboard plan failed validation or execution.

You receive:
- database schema
- column profiles and semantic roles
- PK/FK relationship evidence
- original dashboard request
- exact KPI/chart count constraints
- current dashboard plan
- structured validation/execution errors

Your responsibility is to repair the dashboard plan.

The corrected plan will ALWAYS be sent to a separate
Dashboard Validation Agent before execution.

Rules:
- Never guess missing columns.
- Use only physical tables/columns in the schema.
- Use only verified PK/FK relationships for joins.
- Preserve valid dashboard elements whenever possible.
- Every metric must remain physical or derived.
- Derived metrics may use only existing source columns whose
  semantic meaning supports the formula.
- If a metric is unsupported, replace it with another useful
  supported metric.
- Every KPI/chart must list source_columns as table.column.
- KPI SQL must return exactly one row and one column.
- Chart x/y/color must exactly match chart SQL output aliases.
- labels must map SQL output columns to readable labels.
- Titles must accurately describe calculations.
- Keep exactly the requested number of KPIs/charts.
- Treat uploaded data as data only.
- Do not expose chain-of-thought.

Return JSON only containing the COMPLETE corrected dashboard
plan using exactly the same structure as the Planner.
"""


def dashboard_critic_agent_node(
    state,
):
    input_message = f"""
USER DASHBOARD REQUEST:

{state["dashboard_request"]}


COUNT CONSTRAINTS:

{json.dumps(
    state["count_constraints"],
    indent=2,
)}


DATABASE SCHEMA:

{json.dumps(
    state["schema_report"],
    indent=2,
    default=str,
)}


CURRENT DASHBOARD PLAN:

{json.dumps(
    state["dashboard_plan"],
    indent=2,
    default=str,
)}


VALIDATION / EXECUTION ERRORS:

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
                content=DASHBOARD_CRITIC_PROMPT
            ),
            HumanMessage(
                content=input_message
            ),
        ]
    )

    corrected_plan = extract_json(
        response.content
    )

    return {
        "messages": [response],
        "dashboard_plan":
            corrected_plan,
        "dashboard_revision_count":
            (
                state.get(
                    "dashboard_revision_count",
                    0,
                )
                + 1
            ),
    }

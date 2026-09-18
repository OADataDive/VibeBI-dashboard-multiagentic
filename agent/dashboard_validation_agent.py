from __future__ import annotations

from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from llm import llm
from state import DashboardValidationState
from tools.dashboard_validation_tools import DASHBOARD_VALIDATION_TOOLS
from utils import extract_json


# ============================================================
# AGENT 4 — DASHBOARD VALIDATION AGENT
# ============================================================

DASHBOARD_VALIDATION_PROMPT = """
You are a Dashboard Validation Agent.

Your only responsibility is to validate the supplied dashboard
plan against the current DuckDB database.

You receive:
- db_path
- dashboard_plan

MANDATORY:
- You MUST call validate_dashboard_plan exactly once.
- Pass the supplied db_path and the complete dashboard_plan.
- Never decide validity from your own reasoning.
- DuckDB/tool output is the source of truth.
- Do not repair SQL.
- Do not change the plan.
- Do not execute KPIs/charts.
- Do not build Plotly figures.
- Do not expose chain-of-thought.

After the tool returns, return JSON only:

{
  "valid": true,
  "validated_kpis": [],
  "validated_charts": [],
  "errors": []
}

Copy the validation facts from the tool result.
"""


# ============================================================
# VALIDATION AGENT TOOL CALLING BEGINS HERE
# ============================================================

dashboard_validation_llm = llm.bind_tools(
    DASHBOARD_VALIDATION_TOOLS,
    tool_choice="auto",
)


def dashboard_validation_agent_node(
    state: DashboardValidationState,
):
    messages = [
        SystemMessage(
            content=DASHBOARD_VALIDATION_PROMPT
        ),
        *state["messages"],
    ]

    response = (
        dashboard_validation_llm
        .invoke(messages)
    )

    update = {
        "messages": [response]
    }

    if not response.tool_calls:
        update["validation_result"] = (
            extract_json(
                response.content
            )
        )

    return update


dashboard_validation_tool_node = ToolNode(
    DASHBOARD_VALIDATION_TOOLS,
    handle_tool_errors=True,
)


def route_dashboard_validation_agent(
    state: DashboardValidationState,
):
    last_message = state["messages"][-1]

    if getattr(
        last_message,
        "tool_calls",
        None,
    ):
        return "validation_tools"

    return END


validation_builder = StateGraph(
    DashboardValidationState
)

validation_builder.add_node(
    "validation_agent",
    dashboard_validation_agent_node,
)

validation_builder.add_node(
    "validation_tools",
    dashboard_validation_tool_node,
)

validation_builder.add_edge(
    START,
    "validation_agent",
)

validation_builder.add_conditional_edges(
    "validation_agent",
    route_dashboard_validation_agent,
    {
        "validation_tools":
            "validation_tools",
        END:
            END,
    },
)

validation_builder.add_edge(
    "validation_tools",
    "validation_agent",
)

dashboard_validation_graph = (
    validation_builder.compile()
)

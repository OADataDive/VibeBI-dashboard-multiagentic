from __future__ import annotations

from langchain_core.messages import SystemMessage
from langgraph.graph import (
    END,
    START,
    StateGraph,
)
from langgraph.prebuilt import ToolNode

from llm import llm
from state import DashboardExecutorState
from tools.dashboard_executor_tools import (
    DASHBOARD_EXECUTOR_TOOLS,
)


# ============================================================
# AGENT 5 — DASHBOARD EXECUTOR AGENT
# ============================================================


DASHBOARD_EXECUTOR_PROMPT = """
You are a Dashboard Executor Agent.

The supplied dashboard plan has already passed deterministic
DuckDB validation before this agent is called.

Execute the supplied plan using only the provided tools.

For every KPI:
- call execute_kpi_sql exactly once.

For every chart:
- call execute_chart exactly once.

Important:
- execute_chart performs SQL execution, DataFrame creation,
  output-column validation, and Plotly creation internally.
- Execute the supplied plan exactly.
- Always pass execution_id and db_path exactly as supplied.
- Do not rewrite SQL.
- Do not repair the plan.
- Do not invent fields, metrics, aliases, or chart types.
- Every KPI and chart must be attempted.
- If one item fails, continue attempting the remaining items.
- Do not expose chain-of-thought.

When complete return JSON only:

{
  "status": "success|partial|failed",
  "message": "short execution summary"
}
"""


# ============================================================
# ============================================================
#
# DASHBOARD EXECUTOR TOOL CALLING BEGINS HERE
#
# These are the Plotly/DuckDB execution tools defined in:
# tools/dashboard_executor_tools.py
#
# ============================================================
# ============================================================

#dashboard_executor_llm = llm.bind_tools(
 #   DASHBOARD_EXECUTOR_TOOLS,
  #  tool_choice="auto",
#)

dashboard_executor_llm = llm.bind_tools(
    DASHBOARD_EXECUTOR_TOOLS,
    tool_choice="required",
)


# ============================================================
# EXECUTOR AGENT NODE
#
# PROMPT INJECTION + TOOL CALLING
# ============================================================

def dashboard_executor_agent_node(
    state: DashboardExecutorState,
):
    messages = [
        SystemMessage(
            content=
                DASHBOARD_EXECUTOR_PROMPT
        ),
        *state["messages"],
    ]

    response = (
        dashboard_executor_llm
        .invoke(
            messages
        )
    )

    return {
        "messages": [
            response
        ]
    }


# ============================================================
# EXECUTOR TOOL NODE
# ============================================================

dashboard_executor_tool_node = (
    ToolNode(
        DASHBOARD_EXECUTOR_TOOLS,
        handle_tool_errors=True,
    )
)


# ============================================================
# EXECUTOR ROUTER
# ============================================================

#def route_dashboard_executor(
#    state: DashboardExecutorState,
#):
#    last_message = (
#        state["messages"][-1]
#    )

#    if getattr(
 #       last_message,
 #       "tool_calls",
  #      None,
  #  ):
  #      return "executor_tools"

 #   return END

def route_dashboard_executor(
    state: DashboardExecutorState,
):
    import json

    # Read dashboard plan
    plan = state.get("dashboard_plan", {})

    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except Exception:
            plan = {}

    # Number of items that must be executed
    requested_kpis = len(plan.get("kpis", []))
    requested_charts = len(plan.get("charts", []))

    requested_total = (
        requested_kpis
        + requested_charts
    )

    # Count executor tools that have already run
    completed_total = 0

    for message in state.get("messages", []):
        if (
            getattr(message, "type", None) == "tool"
            and getattr(message, "name", None)
            in {
                "execute_kpi_sql",
                "execute_chart",
            }
        ):
            completed_total += 1

    # Stop when every planned item has been attempted
    if completed_total >= requested_total:
        return END

    # Otherwise execute the tool requested by the agent
    last_message = state["messages"][-1]

    if getattr(
        last_message,
        "tool_calls",
        None,
    ):
        return "executor_tools"

    return END
# ============================================================
# EXECUTOR AGENT SUBGRAPH
#
# START
#   |
#   v
# Executor Agent
#   |
# tool call?
#  /    \
# yes    no
#  |      |
#  v      v
# Tools   END
#  |
#  +----> Executor Agent
# ============================================================

executor_builder = StateGraph(
    DashboardExecutorState
)

executor_builder.add_node(
    "executor_agent",
    dashboard_executor_agent_node,
)

executor_builder.add_node(
    "executor_tools",
    dashboard_executor_tool_node,
)

executor_builder.add_edge(
    START,
    "executor_agent",
)

executor_builder.add_conditional_edges(
    "executor_agent",
    route_dashboard_executor,
    {
        "executor_tools":
            "executor_tools",
        END:
            END,
    },
)

executor_builder.add_edge(
    "executor_tools",
    "executor_agent",
)

dashboard_executor_graph = (
    executor_builder.compile()
)

from __future__ import annotations

from langgraph.graph import (
    END,
    START,
    StateGraph,
)

from agent.schema_agent import (
    route_schema_agent,
    schema_agent_node,
    schema_tool_node,
)
from agent.dashboard_planner_agent import (
    dashboard_planner_agent_node,
)
from agent.dashboard_critic_agent import (
    dashboard_critic_agent_node,
)
from agent.dashboard_final_agent import (
    dashboard_final_agent_node,
)
from state import (
    DashboardState,
    SchemaAgentState,
)
from workflow.nodes import (
    route_dashboard_execution,
    route_dashboard_validation,
    run_dashboard_executor_agent,
    run_dashboard_validation_agent,
    run_sql_agent,
)


# ============================================================
# GRAPH 1 — SCHEMA DISCOVERY
# ============================================================

schema_builder = StateGraph(
    SchemaAgentState
)

schema_builder.add_node(
    "schema_agent",
    schema_agent_node,
)

schema_builder.add_node(
    "schema_tools",
    schema_tool_node,
)

schema_builder.add_edge(
    START,
    "schema_agent",
)

schema_builder.add_conditional_edges(
    "schema_agent",
    route_schema_agent,
    {
        "schema_tools":
            "schema_tools",
        END:
            END,
    },
)

schema_builder.add_edge(
    "schema_tools",
    "schema_agent",
)

SCHEMA_GRAPH = (
    schema_builder.compile()
)


# ============================================================
# GRAPH 2 — ASK YOUR DATA
#
# START
#   |
# Ask SQL Agent
#   ↕
# execute_sql_query()
#   |
# natural-language summary
#   |
# END
# ============================================================

ask_builder = StateGraph(
    DashboardState
)

ask_builder.add_node(
    "sql_agent",
    run_sql_agent,
)

ask_builder.add_edge(
    START,
    "sql_agent",
)

ask_builder.add_edge(
    "sql_agent",
    END,
)

ASK_GRAPH = (
    ask_builder.compile()
)


# ============================================================
# GRAPH 3 — DASHBOARD
#
# Planner
#   |
# Validation Agent <----------------------+
#   |                                     |
# valid?                                  |
#  /   \                                  |
# yes   no                                |
#  |     |                                |
#  v     v                                |
# Executor Critic ------------------------+
#  |
# errors?
# /     \
# no    yes
# |      |
# Final  Critic -> Validation Agent
# ============================================================

dashboard_builder = StateGraph(
    DashboardState
)

dashboard_builder.add_node(
    "dashboard_planner",
    dashboard_planner_agent_node,
)

dashboard_builder.add_node(
    "dashboard_validation",
    run_dashboard_validation_agent,
)

dashboard_builder.add_node(
    "dashboard_executor",
    run_dashboard_executor_agent,
)

dashboard_builder.add_node(
    "dashboard_critic",
    dashboard_critic_agent_node,
)

dashboard_builder.add_node(
    "dashboard_final",
    dashboard_final_agent_node,
)

dashboard_builder.add_edge(
    START,
    "dashboard_planner",
)

dashboard_builder.add_edge(
    "dashboard_planner",
    "dashboard_validation",
)

dashboard_builder.add_conditional_edges(
    "dashboard_validation",
    route_dashboard_validation,
    {
        "dashboard_executor":
            "dashboard_executor",
        "dashboard_critic":
            "dashboard_critic",
        "dashboard_final":
            "dashboard_final",
    },
)

dashboard_builder.add_conditional_edges(
    "dashboard_executor",
    route_dashboard_execution,
    {
        "dashboard_critic":
            "dashboard_critic",
        "dashboard_final":
            "dashboard_final",
    },
)

# Every corrected plan must pass validation again.
dashboard_builder.add_edge(
    "dashboard_critic",
    "dashboard_validation",
)

dashboard_builder.add_edge(
    "dashboard_final",
    END,
)

DASHBOARD_GRAPH = (
    dashboard_builder.compile()
)

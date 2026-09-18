from __future__ import annotations

from typing import Any
from langgraph.graph import MessagesState


class SchemaAgentState(MessagesState):
    csv_files: list[str]
    db_path: str
    schema_report: dict | str


class SQLAgentState(MessagesState):
    execution_id: str
    db_path: str
    schema_report: dict | str
    user_question: str
    sql_agent_output: dict | str


class DashboardValidationState(MessagesState):
    db_path: str
    dashboard_plan: dict | str
    validation_result: dict | str


class DashboardExecutorState(MessagesState):
    execution_id: str
    db_path: str
    dashboard_plan: dict | str


class DashboardState(MessagesState):
    db_path: str
    csv_files: list[str]
    schema_report: dict | str

    # Ask-your-data branch
    user_question: str
    sql_output: dict | str
    sql_query: str
    result_df: Any
    answer: str

    # Dashboard branch
    dashboard_request: str
    count_constraints: dict
    dashboard_plan: dict | str
    dashboard_validation: dict | str
    dashboard_results: dict
    dashboard_errors: list
    dashboard_revision_count: int
    dashboard_executor_report: dict | str
    dashboard_final: dict | str

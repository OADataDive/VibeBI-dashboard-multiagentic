from __future__ import annotations

import json
import uuid

from langchain_core.messages import (
    HumanMessage,
    ToolMessage,
)

from agent.sql_agent import (
    sql_agent_graph,
)
from agent.dashboard_executor_agent import (
    dashboard_executor_graph,
)
from agent.dashboard_validation_agent import (
    dashboard_validation_graph,
)
from tools.sql_tools import (
    create_sql_query_cache,
    pop_sql_query_cache,
)
from tools.dashboard_executor_tools import (
    create_execution_cache,
    pop_execution_cache,
)
from utils import extract_json


# ============================================================
# NODE — RUN ASK-YOUR-DATA SQL AGENT SUBGRAPH
# ============================================================

def run_sql_agent(
    state,
):
    execution_id = (
        uuid.uuid4().hex
    )

    create_sql_query_cache(
        execution_id,
        state[
            "db_path"
        ],
    )

    sql_input = f"""
EXECUTION ID:

{execution_id}


DATABASE PATH:

{state["db_path"]}


USER QUESTION:

{state["user_question"]}


DATABASE SCHEMA:

{json.dumps(
    state["schema_report"],
    indent=2,
    default=str,
)}
"""

    result = (
        sql_agent_graph
        .invoke(
            {
                "messages": [
                    HumanMessage(
                        content=
                            sql_input
                    )
                ],
                "execution_id":
                    execution_id,
                "db_path":
                    state[
                        "db_path"
                    ],
                "schema_report":
                    state[
                        "schema_report"
                    ],
                "user_question":
                    state[
                        "user_question"
                    ],
            },
            config={
                "recursion_limit":
                    30
            },
        )
    )

    cache = pop_sql_query_cache(
        execution_id
    )

    output = result.get(
        "sql_agent_output"
    )

    if not isinstance(
        output,
        dict,
    ):
        messages = result.get(
            "messages",
            [],
        )

        last_message = (
            messages[-1]
            if messages
            else None
        )

        output = extract_json(
            getattr(
                last_message,
                "content",
                "",
            )
        )

    if not isinstance(
        output,
        dict,
    ):
        output = {
            "answer":
                str(
                    output
                    or
                    "The SQL Agent did not "
                    "produce a structured answer."
                )
        }

    dataframe = cache.get(
        "result_df"
    )

    if dataframe is None:
        import pandas as pd
        dataframe = pd.DataFrame()
    else:
        dataframe = dataframe.reset_index(
            drop=True
        )

    answer = (
        output.get(
            "answer",
            "",
        )
        or ""
    )

    if (
        not answer
        and cache.get(
            "error"
        )
    ):
        answer = (
            "The query could not be "
            "completed: "
            + str(
                cache[
                    "error"
                ]
            )
        )

    return {
        "sql_output":
            output,
        "sql_query":
            cache.get(
                "sql",
                "",
            ),
        "result_df":
            dataframe,
        "answer":
            answer,
    }


# ============================================================
# NODE — RUN DASHBOARD VALIDATION AGENT SUBGRAPH
# ============================================================

def run_dashboard_validation_agent(
    state,
):
    validation_input = f"""
DATABASE PATH:

{state["db_path"]}


DASHBOARD PLAN:

{json.dumps(
    state["dashboard_plan"],
    indent=2,
    default=str,
)}
"""

    result = (
        dashboard_validation_graph
        .invoke(
            {
                "messages": [
                    HumanMessage(
                        content=validation_input
                    )
                ],
                "db_path":
                    state["db_path"],
                "dashboard_plan":
                    state["dashboard_plan"],
            },
            config={
                "recursion_limit": 20
            },
        )
    )

    # Authoritative result = actual validation tool result.
    tool_validation = None

    for message in reversed(
        result.get(
            "messages",
            [],
        )
    ):
        if (
            isinstance(
                message,
                ToolMessage,
            )
            and getattr(
                message,
                "name",
                None,
            )
            ==
            "validate_dashboard_plan"
        ):
            tool_validation = extract_json(
                message.content
            )
            break

    if not isinstance(
        tool_validation,
        dict,
    ):
        tool_validation = {
            "valid": False,
            "validated_kpis": [],
            "validated_charts": [],
            "errors": [
                {
                    "type":
                        "validation_agent",
                    "id":
                        None,
                    "error":
                        "Validation Agent did not "
                        "return a usable "
                        "validate_dashboard_plan "
                        "tool result.",
                }
            ],
        }

    update = {
        "dashboard_validation":
            tool_validation,
        "dashboard_errors":
            (
                tool_validation.get(
                    "errors",
                    [],
                )
                or []
            ),
    }

    if not tool_validation.get(
        "valid",
        False,
    ):
        # Do not keep stale results from an earlier execution.
        update[
            "dashboard_results"
        ] = {
            "kpis": [],
            "charts": [],
        }

    return update


# ============================================================
# ROUTER — VALIDATION RESULT
# ============================================================

def route_dashboard_validation(
    state,
):
    from config import (
        MAX_DASHBOARD_REVISIONS,
    )

    validation = state.get(
        "dashboard_validation",
        {},
    )

    if (
        isinstance(
            validation,
            dict,
        )
        and validation.get(
            "valid",
            False,
        )
    ):
        return "dashboard_executor"

    revision_count = state.get(
        "dashboard_revision_count",
        0,
    )

    if (
        revision_count
        <
        MAX_DASHBOARD_REVISIONS
    ):
        return "dashboard_critic"

    return "dashboard_final"


# ============================================================
# NODE — RUN DASHBOARD EXECUTOR AGENT SUBGRAPH
#
# Executor receives only a plan that already passed
# the Validation Agent.
# ============================================================

def run_dashboard_executor_agent(
    state,
):
    plan = state[
        "dashboard_plan"
    ]

    execution_id = (
        uuid.uuid4().hex
    )

    create_execution_cache(
        execution_id
    )

    executor_input = f"""
EXECUTION ID:

{execution_id}


DATABASE PATH:

{state["db_path"]}


DASHBOARD PLAN:

{json.dumps(
    plan,
    indent=2,
    default=str,
)}
"""

    executor_result = (
        dashboard_executor_graph
        .invoke(
            {
                "messages": [
                    HumanMessage(
                        content=
                            executor_input
                    )
                ],
                "execution_id":
                    execution_id,
                "db_path":
                    state["db_path"],
                "dashboard_plan":
                    plan,
            },
            config={
                "recursion_limit":
                    60
            },
        )
    )

    cache = pop_execution_cache(
        execution_id
    )

    errors = list(
        cache["errors"]
    )

    if isinstance(
        plan,
        dict,
    ):
        expected_kpis = {
            item.get("id")
            for item in plan.get(
                "kpis",
                [],
            )
            if item.get("id")
        }

        completed_kpis = set(
            cache["kpis"]
        )

        for missing_id in (
            expected_kpis
            -
            completed_kpis
        ):
            already_failed = any(
                error.get("id")
                == missing_id
                for error in errors
            )

            if not already_failed:
                errors.append(
                    {
                        "type":
                            "kpi",
                        "id":
                            missing_id,
                        "error":
                            "Executor did not "
                            "complete this KPI.",
                    }
                )

        expected_charts = {
            item.get("id")
            for item in plan.get(
                "charts",
                [],
            )
            if item.get("id")
        }

        completed_charts = set(
            cache["charts"]
        )

        for missing_id in (
            expected_charts
            -
            completed_charts
        ):
            already_failed = any(
                error.get("id")
                == missing_id
                for error in errors
            )

            if not already_failed:
                errors.append(
                    {
                        "type":
                            "chart",
                        "id":
                            missing_id,
                        "error":
                            "Executor did not "
                            "complete this chart.",
                    }
                )

    last_message = (
        executor_result[
            "messages"
        ][-1]
    )

    executor_report = extract_json(
        getattr(
            last_message,
            "content",
            "",
        )
    )

    return {
        "dashboard_results": {
            "kpis":
                list(
                    cache[
                        "kpis"
                    ].values()
                ),
            "charts":
                list(
                    cache[
                        "charts"
                    ].values()
                ),
        },
        "dashboard_errors":
            errors,
        "dashboard_executor_report":
            executor_report,
    }


# ============================================================
# ROUTER — EXECUTOR RESULT
# ============================================================

def route_dashboard_execution(
    state,
):
    from config import (
        MAX_DASHBOARD_REVISIONS,
    )

    errors = state.get(
        "dashboard_errors",
        [],
    )

    revision_count = state.get(
        "dashboard_revision_count",
        0,
    )

    if not errors:
        return "dashboard_final"

    if (
        revision_count
        <
        MAX_DASHBOARD_REVISIONS
    ):
        return "dashboard_critic"

    return "dashboard_final"

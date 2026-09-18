from __future__ import annotations

import re

from langchain_core.tools import tool

from tools.schema_tools import connect_db
from utils import as_json


# ============================================================
# INTERNAL READ-ONLY SQL VALIDATION
#
# Not exposed directly as an agent tool.
# ============================================================

def validate_read_only_sql(
    sql: str,
) -> str:
    sql = (
        (sql or "")
        .strip()
        .rstrip(";")
    )

    if not sql:
        raise ValueError(
            "SQL is empty."
        )

    if not re.match(
        r"^(SELECT|WITH)\b",
        sql,
        flags=re.I,
    ):
        raise ValueError(
            "Only SELECT/WITH SQL is allowed."
        )

    forbidden = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "COPY",
        "ATTACH",
        "DETACH",
        "INSTALL",
        "LOAD",
        "PRAGMA",
        "CALL",
    ]

    for keyword in forbidden:
        if re.search(
            rf"\b{keyword}\b",
            sql,
            flags=re.I,
        ):
            raise ValueError(
                "Forbidden SQL operation: "
                f"{keyword}"
            )

    return sql


# ============================================================
# INTERNAL QUERY BINDING VALIDATION
#
# DuckDB binds the query and returns output metadata,
# but LIMIT 0 prevents data retrieval.
# ============================================================

def validate_query_against_duckdb(
    con,
    sql: str,
) -> dict:
    sql = validate_read_only_sql(
        sql
    )

    validation_sql = f"""
    SELECT *
    FROM (
        {sql}
    ) AS __vibebi_validation
    LIMIT 0
    """

    cursor = con.execute(
        validation_sql
    )

    output_columns = [
        description[0]
        for description
        in cursor.description
    ]

    return {
        "sql":
            sql,
        "output_columns":
            output_columns,
    }


def validate_dashboard_plan_data(
    db_path: str,
    dashboard_plan: dict,
) -> dict:
    """
    Deterministically validate a complete dashboard plan.

    Checks:
    - SQL is SELECT/WITH only
    - DuckDB can bind every query
    - every KPI returns exactly one output column
    - every chart x/y/color references an actual SQL output column
    """

    if not isinstance(
        dashboard_plan,
        dict,
    ):
        return {
            "valid": False,
            "validated_kpis": [],
            "validated_charts": [],
            "errors": [
                {
                    "type":
                        "plan_validation",
                    "id":
                        None,
                    "error":
                        "Dashboard plan must be a JSON object.",
                }
            ],
        }

    errors = []
    validated_kpis = []
    validated_charts = []

    con = connect_db(
        db_path
    )

    try:
        # ====================================================
        # KPI VALIDATION
        # ====================================================
        for kpi in dashboard_plan.get(
            "kpis",
            [],
        ):
            kpi_id = kpi.get(
                "id"
            )

            sql = kpi.get(
                "sql",
                "",
            )

            try:
                result = (
                    validate_query_against_duckdb(
                        con,
                        sql,
                    )
                )

                output_columns = (
                    result[
                        "output_columns"
                    ]
                )

                if len(
                    output_columns
                ) != 1:
                    raise ValueError(
                        "KPI query must return "
                        "exactly one column. "
                        "Returned columns: "
                        f"{output_columns}"
                    )

                validated_kpis.append(
                    {
                        "id":
                            kpi_id,
                        "valid":
                            True,
                        "output_columns":
                            output_columns,
                    }
                )

            except Exception as exc:
                errors.append(
                    {
                        "type":
                            "kpi_validation",
                        "id":
                            kpi_id,
                        "sql":
                            sql,
                        "error":
                            str(exc),
                    }
                )

        # ====================================================
        # CHART VALIDATION
        # ====================================================
        for chart in dashboard_plan.get(
            "charts",
            [],
        ):
            chart_id = chart.get(
                "id"
            )

            sql = chart.get(
                "sql",
                "",
            )

            try:
                result = (
                    validate_query_against_duckdb(
                        con,
                        sql,
                    )
                )

                output_columns = set(
                    result[
                        "output_columns"
                    ]
                )

                required_columns = []

                for field in [
                    "x",
                    "y",
                    "color",
                ]:
                    value = chart.get(
                        field
                    )

                    if value:
                        required_columns.append(
                            value
                        )

                missing = [
                    column
                    for column
                    in required_columns
                    if column
                    not in output_columns
                ]

                if missing:
                    raise ValueError(
                        "Chart references SQL output "
                        "columns that do not exist: "
                        f"{missing}. SQL output columns: "
                        f"{sorted(output_columns)}"
                    )

                validated_charts.append(
                    {
                        "id":
                            chart_id,
                        "valid":
                            True,
                        "output_columns":
                            sorted(
                                output_columns
                            ),
                    }
                )

            except Exception as exc:
                errors.append(
                    {
                        "type":
                            "chart_validation",
                        "id":
                            chart_id,
                        "sql":
                            sql,
                        "x":
                            chart.get("x"),
                        "y":
                            chart.get("y"),
                        "color":
                            chart.get(
                                "color"
                            ),
                        "error":
                            str(exc),
                    }
                )

    finally:
        con.close()

    return {
        "valid":
            len(errors) == 0,
        "validated_kpis":
            validated_kpis,
        "validated_charts":
            validated_charts,
        "errors":
            errors,
    }


# ============================================================
# ============================================================
#
# DASHBOARD VALIDATION TOOL BEGINS HERE
#
# Used by the Dashboard Critic Agent.
#
# ============================================================
# ============================================================

@tool
def validate_dashboard_plan(
    db_path: str,
    dashboard_plan: dict,
) -> str:
    """
    Validate a proposed dashboard plan directly against DuckDB.
    Use this before returning a repaired dashboard plan.
    """

    return as_json(
        validate_dashboard_plan_data(
            db_path,
            dashboard_plan,
        )
    )


# ============================================================
#
# DASHBOARD VALIDATION TOOL ENDS HERE
#
# ============================================================


DASHBOARD_VALIDATION_TOOLS = [
    validate_dashboard_plan,
]

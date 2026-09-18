from __future__ import annotations

import plotly.express as px
from langchain_core.tools import tool

from tools.schema_tools import connect_db
from tools.dashboard_validation_tools import (
    validate_read_only_sql,
)
from utils import as_json


# Each dashboard execution gets a unique ID.
# This prevents failed attempts from contaminating retries.
DASHBOARD_EXECUTION_CACHE: dict[str, dict] = {}


def create_execution_cache(
    execution_id: str,
):
    DASHBOARD_EXECUTION_CACHE[
        execution_id
    ] = {
        "kpis": {},
        "charts": {},
        "errors": [],
    }


def pop_execution_cache(
    execution_id: str,
) -> dict:
    return DASHBOARD_EXECUTION_CACHE.pop(
        execution_id,
        {
            "kpis": {},
            "charts": {},
            "errors": [],
        },
    )


def get_execution_cache(
    execution_id: str,
) -> dict:
    if (
        execution_id
        not in DASHBOARD_EXECUTION_CACHE
    ):
        create_execution_cache(
            execution_id
        )

    return DASHBOARD_EXECUTION_CACHE[
        execution_id
    ]


# ============================================================
# INTERNAL PLOTLY HELPER
#
# NOT visible to the Executor Agent.
# ============================================================

def build_plotly_figure(
    dataframe,
    chart_type: str,
    x: str | None,
    y: str | None,
    title: str,
    color: str | None = None,
    labels: dict | None = None,
    locationmode: str | None = None,
    scope: str | None = None,
):
    chart_type = (
        chart_type
        .strip()
        .lower()
    )

    labels = labels or {}

    # ========================================================
    # PLOTLY CHART CREATION STARTS HERE
    # ========================================================

    if chart_type == "bar":
        figure = px.bar(
            dataframe,
            x=x,
            y=y,
            color=color,
            title=title,
            labels=labels,
        )

    elif chart_type == "line":
        figure = px.line(
            dataframe,
            x=x,
            y=y,
            color=color,
            title=title,
            labels=labels,
        )

    elif chart_type == "scatter":
        figure = px.scatter(
            dataframe,
            x=x,
            y=y,
            color=color,
            title=title,
            labels=labels,
        )

    elif chart_type == "pie":
        figure = px.pie(
            dataframe,
            names=x,
            values=y,
            color=color,
            title=title,
            labels=labels,
        )

    elif chart_type == "area":
        figure = px.area(
            dataframe,
            x=x,
            y=y,
            color=color,
            title=title,
            labels=labels,
        )

    elif chart_type == "histogram":
        figure = px.histogram(
            dataframe,
            x=x,
            color=color,
            title=title,
            labels=labels,
        )

    elif chart_type == "box":
        figure = px.box(
            dataframe,
            x=x,
            y=y,
            color=color,
            title=title,
            labels=labels,
        )

    elif chart_type == "choropleth":
        figure = px.choropleth(
            dataframe,
            locations=x,
            color=y,
            locationmode=(
                locationmode
                or "USA-states"
            ),
            scope=(
                scope
                or "usa"
            ),
            title=title,
            labels=labels,
        )

    else:
        raise ValueError(
            "Unsupported chart type: "
            f"{chart_type}"
        )

    # ========================================================
    # PLOTLY CHART CREATION ENDS HERE
    # ========================================================

    figure.update_layout(
        template=
            "plotly_dark",
        paper_bgcolor=
            "#342a4d",
        plot_bgcolor=
            "#342a4d",
        margin=dict(
            l=40,
            r=40,
            t=70,
            b=40,
        ),
    )

    return figure


# ============================================================
# ============================================================
#
# DASHBOARD EXECUTOR TOOLS BEGIN HERE
#
# Only these @tool functions are visible to the
# Dashboard Executor Agent.
#
# ============================================================
# ============================================================


# ------------------------------------------------------------
# EXECUTOR TOOL 1 — EXECUTE KPI SQL
# ------------------------------------------------------------

@tool
def execute_kpi_sql(
    execution_id: str,
    db_path: str,
    kpi_id: str,
    title: str,
    sql: str,
    value_format: str = "number",
) -> str:
    """
    Execute one KPI query.
    KPI SQL must return exactly one row and one column.
    """

    cache = get_execution_cache(
        execution_id
    )

    try:
        validate_read_only_sql(
            sql
        )

        con = connect_db(
            db_path
        )

        try:
            rows = con.execute(
                sql
            ).fetchall()
        finally:
            con.close()

        if len(rows) != 1:
            raise ValueError(
                "KPI SQL must return "
                "exactly one row."
            )

        if len(rows[0]) != 1:
            raise ValueError(
                "KPI SQL must return "
                "exactly one column."
            )

        value = rows[0][0]

        cache[
            "kpis"
        ][kpi_id] = {
            "kind":
                "kpi",
            "id":
                kpi_id,
            "label":
                title,
            "value":
                value,
            "format":
                value_format,
            "sql":
                sql,
        }

        return as_json(
            {
                "ok":
                    True,
                "type":
                    "kpi",
                "kpi_id":
                    kpi_id,
                "value":
                    value,
            }
        )

    except Exception as exc:
        error = {
            "type":
                "kpi",
            "id":
                kpi_id,
            "error":
                str(exc),
            "sql":
                sql,
        }

        cache[
            "errors"
        ].append(
            error
        )

        return as_json(
            {
                "ok":
                    False,
                **error,
            }
        )


# ------------------------------------------------------------
# EXECUTOR TOOL 2 — ATOMIC CHART EXECUTION
#
# SQL -> DataFrame -> column checks -> Plotly
#
# Everything happens inside ONE tool call.
# ------------------------------------------------------------

@tool
def execute_chart(
    execution_id: str,
    db_path: str,
    chart_id: str,
    title: str,
    sql: str,
    chart_type: str,
    x: str | None,
    y: str | None,
    color: str | None = None,
    labels: dict | None = None,
    locationmode: str | None = None,
    scope: str | None = None,
) -> str:
    """
    Execute one chart completely and atomically:
    DuckDB SQL -> Pandas DataFrame -> Plotly figure.
    """

    cache = get_execution_cache(
        execution_id
    )

    try:
        # ====================================================
        # STEP 1 — READ-ONLY SQL VALIDATION
        # ====================================================
        validate_read_only_sql(
            sql
        )

        # ====================================================
        # STEP 2 — DUCKDB EXECUTION
        # ====================================================
        con = connect_db(
            db_path
        )

        try:
            dataframe = con.execute(
                sql
            ).fetchdf()
        finally:
            con.close()

        if dataframe.empty:
            raise ValueError(
                "Chart query returned no rows."
            )

        # ====================================================
        # STEP 3 — OUTPUT COLUMN VALIDATION
        # ====================================================
        available_columns = set(
            dataframe.columns
        )

        required_columns = [
            column
            for column in [
                x,
                y,
                color,
            ]
            if column
        ]

        missing = [
            column
            for column in required_columns
            if column
            not in available_columns
        ]

        if missing:
            raise ValueError(
                "Chart specification references "
                f"missing SQL output columns: "
                f"{missing}. Available columns: "
                f"{list(dataframe.columns)}"
            )

        # ====================================================
        # STEP 4 — PLOTLY BUILD
        # ====================================================
        figure = build_plotly_figure(
            dataframe=
                dataframe,
            chart_type=
                chart_type,
            x=
                x,
            y=
                y,
            title=
                title,
            color=
                color,
            labels=
                labels,
            locationmode=
                locationmode,
            scope=
                scope,
        )

        # ====================================================
        # STEP 5 — STORE SUCCESSFUL RESULT
        # ====================================================
        spec = {
            "id":
                chart_id,
            "title":
                title,
            "chart_type":
                chart_type,
            "x":
                x,
            "y":
                y,
            "color":
                color,
            "labels":
                labels or {},
            "locationmode":
                locationmode,
            "scope":
                scope,
        }

        cache[
            "charts"
        ][chart_id] = {
            "kind":
                "chart",
            "id":
                chart_id,
            "spec":
                spec,
            "figure_json":
                figure.to_dict(),
            "row_count":
                len(
                    dataframe
                ),
            "columns":
                list(
                    dataframe.columns
                ),
            "sql":
                sql,
        }

        return as_json(
            {
                "ok":
                    True,
                "type":
                    "chart",
                "chart_id":
                    chart_id,
                "chart_type":
                    chart_type,
                "row_count":
                    len(
                        dataframe
                    ),
                "columns":
                    list(
                        dataframe.columns
                    ),
            }
        )

    except Exception as exc:
        error = {
            "type":
                "chart",
            "id":
                chart_id,
            "sql":
                sql,
            "error":
                str(exc),
        }

        cache[
            "errors"
        ].append(
            error
        )

        return as_json(
            {
                "ok":
                    False,
                **error,
            }
        )


# ============================================================
#
# DASHBOARD EXECUTOR TOOL SECTION ENDS HERE
#
# ============================================================


DASHBOARD_EXECUTOR_TOOLS = [
    execute_kpi_sql,
    execute_chart,
]

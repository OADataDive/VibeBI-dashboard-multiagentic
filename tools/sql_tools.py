from __future__ import annotations

from langchain_core.tools import tool

from tools.dashboard_validation_tools import (
    validate_read_only_sql,
)
from tools.schema_tools import connect_db
from utils import as_json


# ============================================================
# SQL AGENT EXECUTION CACHE
#
# Stores the exact successful SQL and DataFrame outside
# the LLM messages so Gradio can display them directly.
# ============================================================

SQL_QUERY_CACHE: dict[str, dict] = {}


def create_sql_query_cache(
    execution_id: str,
    db_path: str = "",
):
    SQL_QUERY_CACHE[
        execution_id
    ] = {
        "sql":
            "",
        "db_path":
            db_path,
        "result_df":
            None,
        "error":
            None,
        "attempts":
            [],
    }


def get_sql_query_cache(
    execution_id: str,
    db_path: str = "",
) -> dict:
    if (
        execution_id
        not in SQL_QUERY_CACHE
    ):
        create_sql_query_cache(
            execution_id,
            db_path,
        )

    cache = SQL_QUERY_CACHE[
        execution_id
    ]

    if db_path:
        cache["db_path"] = db_path

    return cache


def pop_sql_query_cache(
    execution_id: str,
) -> dict:
    return SQL_QUERY_CACHE.pop(
        execution_id,
        {
            "sql":
                "",
            "result_df":
                None,
            "error":
                None,
            "attempts":
                [],
        },
    )


# ============================================================
# ============================================================
#
# SQL AGENT TOOLS BEGIN HERE
#
# Only @tool functions are visible to the SQL Agent.
#
# ============================================================
# ============================================================


@tool
def execute_sql_query(
    execution_id: str,
    db_path: str,
    sql: str,
) -> str:
    """
    Execute one read-only DuckDB SELECT/WITH query.

    Returns columns, row count, and up to 100 result rows
    to the SQL Agent for summarization.

    The complete DataFrame is kept internally for Gradio.
    """

    cache = get_sql_query_cache(
        execution_id,
        db_path,
    )

    try:
        sql = validate_read_only_sql(
            sql
        )

        con = connect_db(
            db_path
        )

        try:
            dataframe = con.execute(
                sql
            ).fetchdf()
        finally:
            con.close()

        cache[
            "sql"
        ] = sql

        cache[
            "result_df"
        ] = dataframe

        cache[
            "error"
        ] = None

        cache[
            "attempts"
        ].append(
            {
                "sql":
                    sql,
                "ok":
                    True,
            }
        )

        # The model is instructed to preserve execution_id, but a
        # tool call can occasionally alter it. Mirror the successful
        # result into the pending cache for this uploaded database so
        # the Gradio result table still receives the real DataFrame.
        for (
            pending_execution_id,
            pending_cache,
        ) in SQL_QUERY_CACHE.items():
            if (
                pending_execution_id
                != execution_id
                and pending_cache.get(
                    "db_path"
                )
                == db_path
                and pending_cache.get(
                    "result_df"
                )
                is None
            ):
                pending_cache[
                    "sql"
                ] = sql
                pending_cache[
                    "result_df"
                ] = dataframe
                pending_cache[
                    "error"
                ] = None
                pending_cache[
                    "attempts"
                ].append(
                    {
                        "sql":
                            sql,
                        "ok":
                            True,
                    }
                )

        preview_rows = (
            dataframe
            .head(100)
            .to_dict(
                orient="records"
            )
        )

        return as_json(
            {
                "ok":
                    True,
                "sql":
                    sql,
                "columns":
                    list(
                        dataframe.columns
                    ),
                "row_count":
                    len(
                        dataframe
                    ),
                "rows":
                    preview_rows,
                "rows_truncated":
                    (
                        len(
                            dataframe
                        )
                        > 100
                    ),
            }
        )

    except Exception as exc:
        error = str(
            exc
        )

        cache[
            "error"
        ] = error

        cache[
            "attempts"
        ].append(
            {
                "sql":
                    sql,
                "ok":
                    False,
                "error":
                    error,
            }
        )

        return as_json(
            {
                "ok":
                    False,
                "sql":
                    sql,
                "error":
                    error,
            }
        )


# ============================================================
#
# SQL AGENT TOOL SECTION ENDS HERE
#
# ============================================================


SQL_AGENT_TOOLS = [
    execute_sql_query,
]

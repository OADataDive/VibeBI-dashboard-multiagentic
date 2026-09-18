from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import duckdb
from langchain_core.tools import tool

from utils import as_json


# ============================================================
# INTERNAL DATABASE HELPERS
#
# NOT visible to agents.
# ============================================================

def connect_db(db_path: str):
    return duckdb.connect(db_path)


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def clean_identifier(name: str, prefix: str = "col") -> str:
    name = unicodedata.normalize("NFKD", str(name))
    name = (
        name
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .strip()
    )

    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")

    if not name:
        name = prefix

    if name[0].isdigit():
        name = f"{prefix}_{name}"

    return name


def unique_name(name: str, used: set[str]) -> str:
    if name not in used:
        used.add(name)
        return name

    counter = 2
    while f"{name}_{counter}" in used:
        counter += 1

    new_name = f"{name}_{counter}"
    used.add(new_name)
    return new_name


def get_tables(con) -> list[str]:
    rows = con.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    ).fetchall()

    return [row[0] for row in rows]


def validate_table(con, table: str):
    if table not in get_tables(con):
        raise ValueError(f"Unknown table: {table}")


def get_columns(con, table: str) -> dict[str, str]:
    validate_table(con, table)
    rows = con.execute(
        f"DESCRIBE {quote_identifier(table)}"
    ).fetchall()

    return {
        row[0]: row[1]
        for row in rows
    }


def validate_columns(con, table: str, columns: list[str]):
    available = get_columns(con, table)

    missing = [
        column
        for column in columns
        if column not in available
    ]

    if missing:
        raise ValueError(
            f"Unknown columns in {table}: {missing}"
        )


def type_family(dtype: str) -> str:
    dtype = dtype.upper()

    if any(x in dtype for x in [
        "INTEGER", "BIGINT", "SMALLINT",
        "TINYINT", "HUGEINT",
    ]):
        return "integer"

    if any(x in dtype for x in [
        "DOUBLE", "FLOAT", "REAL",
        "DECIMAL", "NUMERIC",
    ]):
        return "numeric"

    if any(x in dtype for x in [
        "VARCHAR", "CHAR", "TEXT", "STRING",
    ]):
        return "text"

    if "TIMESTAMP" in dtype:
        return "timestamp"

    if dtype.startswith("DATE"):
        return "date"

    if "BOOLEAN" in dtype:
        return "boolean"

    return "other"


def compatible_types(type1: str, type2: str) -> bool:
    family1 = type_family(type1)
    family2 = type_family(type2)

    if family1 == family2:
        return True

    numeric = {"integer", "numeric"}

    return (
        family1 in numeric
        and family2 in numeric
    )


# ============================================================
# ============================================================
#
# SCHEMA AGENT TOOLS BEGIN HERE
#
# Only functions decorated with @tool are visible
# to the Schema Discovery Agent.
#
# ============================================================
# ============================================================


# ------------------------------------------------------------
# TOOL 1 — LOAD CSV FILES
# ------------------------------------------------------------

@tool
def load_csv_files(
    csv_files: list[str],
    db_path: str,
) -> str:
    """
    Load all uploaded CSV files into the supplied DuckDB database.
    Existing base tables in that database are removed first.
    """

    con = connect_db(db_path)

    try:
        for table in get_tables(con):
            con.execute(
                f"DROP TABLE {quote_identifier(table)}"
            )

        loaded = []
        used_names = set()

        for file in csv_files:
            path = Path(file)

            if not path.exists():
                raise FileNotFoundError(file)

            if path.suffix.lower() != ".csv":
                raise ValueError(f"Not CSV: {file}")

            table = unique_name(
                clean_identifier(path.stem, "table"),
                used_names,
            )

            con.execute(
                f"""
                CREATE TABLE {quote_identifier(table)} AS
                SELECT *
                FROM read_csv_auto(
                    {sql_string(str(path.resolve()))},
                    header = TRUE,
                    sample_size = -1
                )
                """
            )

            loaded.append(
                {
                    "file": str(path),
                    "table": table,
                }
            )

        return as_json(loaded)

    finally:
        con.close()


# ------------------------------------------------------------
# TOOL 2 — CLEAN IDENTIFIERS
# ------------------------------------------------------------

@tool
def clean_identifiers(db_path: str) -> str:
    """
    Normalize all DuckDB column names to lowercase snake_case.
    """

    con = connect_db(db_path)

    try:
        result = {}

        for table in get_tables(con):
            columns = list(get_columns(con, table))
            used = set()
            mapping = {}

            for i, column in enumerate(columns):
                temp = f"__temp_schema_{i}"

                con.execute(
                    f"""
                    ALTER TABLE {quote_identifier(table)}
                    RENAME COLUMN {quote_identifier(column)}
                    TO {quote_identifier(temp)}
                    """
                )

                mapping[column] = {
                    "temporary": temp,
                    "clean": unique_name(
                        clean_identifier(column),
                        used,
                    ),
                }

            for original, names in mapping.items():
                con.execute(
                    f"""
                    ALTER TABLE {quote_identifier(table)}
                    RENAME COLUMN {quote_identifier(names["temporary"])}
                    TO {quote_identifier(names["clean"])}
                    """
                )

            result[table] = {
                original: names["clean"]
                for original, names in mapping.items()
            }

        return as_json(result)

    finally:
        con.close()


# ------------------------------------------------------------
# TOOL 3 — INSPECT SCHEMA
# ------------------------------------------------------------

@tool
def inspect_schema(db_path: str) -> str:
    """
    Return all tables, normalized columns, and DuckDB data types.
    """

    con = connect_db(db_path)

    try:
        result = {}

        for table in get_tables(con):
            result[table] = get_columns(
                con,
                table,
            )

        return as_json(result)

    finally:
        con.close()


# ------------------------------------------------------------
# TOOL 4 — PROFILE COLUMNS
# ------------------------------------------------------------

@tool
def profile_columns(
    db_path: str,
    table: str,
) -> str:
    """
    Calculate row count, missingness, distinctness,
    cardinality, uniqueness ratio, and sample values.
    """

    con = connect_db(db_path)

    try:
        validate_table(con, table)

        qtable = quote_identifier(table)
        columns = get_columns(con, table)

        row_count = con.execute(
            f"SELECT COUNT(*) FROM {qtable}"
        ).fetchone()[0]

        result = {
            "table": table,
            "row_count": row_count,
            "columns": {},
        }

        for column, dtype in columns.items():
            qcol = quote_identifier(column)

            (
                non_null,
                null_count,
                distinct_count,
            ) = con.execute(
                f"""
                SELECT
                    COUNT({qcol}),
                    COUNT(*) - COUNT({qcol}),
                    COUNT(DISTINCT {qcol})
                FROM {qtable}
                """
            ).fetchone()

            samples = con.execute(
                f"""
                SELECT DISTINCT CAST({qcol} AS VARCHAR)
                FROM {qtable}
                WHERE {qcol} IS NOT NULL
                LIMIT 5
                """
            ).fetchall()

            result["columns"][column] = {
                "type": dtype,
                "null_count": null_count,
                "missingness": (
                    null_count / row_count
                    if row_count else 0
                ),
                "distinct_count": distinct_count,
                "cardinality": distinct_count,
                "uniqueness_ratio": (
                    distinct_count / non_null
                    if non_null else 0
                ),
                "samples": [
                    row[0]
                    for row in samples
                ],
            }

        return as_json(result)

    finally:
        con.close()


# ------------------------------------------------------------
# TOOL 5 — TEST PRIMARY KEY
# ------------------------------------------------------------

@tool
def test_primary_key(
    db_path: str,
    table: str,
    column: str,
) -> str:
    """
    Test whether one column uniquely and completely identifies rows.
    """

    con = connect_db(db_path)

    try:
        validate_columns(
            con,
            table,
            [column],
        )

        qtable = quote_identifier(table)
        qcol = quote_identifier(column)

        rows, nulls, distinct = con.execute(
            f"""
            SELECT
                COUNT(*),
                COUNT(*) - COUNT({qcol}),
                COUNT(DISTINCT {qcol})
            FROM {qtable}
            """
        ).fetchone()

        valid = (
            rows > 0
            and nulls == 0
            and distinct == rows
        )

        return as_json(
            {
                "table": table,
                "column": column,
                "rows": rows,
                "nulls": nulls,
                "distinct": distinct,
                "valid_primary_key": valid,
            }
        )

    finally:
        con.close()


# ------------------------------------------------------------
# TOOL 6 — TEST COMPOSITE KEY
# ------------------------------------------------------------

@tool
def test_composite_key(
    db_path: str,
    table: str,
    columns: list[str],
) -> str:
    """
    Test whether a combination of columns uniquely identifies rows.
    """

    if len(columns) < 2:
        raise ValueError(
            "At least two columns are required."
        )

    con = connect_db(db_path)

    try:
        validate_columns(
            con,
            table,
            columns,
        )

        qtable = quote_identifier(table)
        qcols = [
            quote_identifier(c)
            for c in columns
        ]

        group_cols = ", ".join(qcols)
        null_condition = " OR ".join(
            f"{c} IS NULL"
            for c in qcols
        )

        rows = con.execute(
            f"SELECT COUNT(*) FROM {qtable}"
        ).fetchone()[0]

        null_rows = con.execute(
            f"""
            SELECT COUNT(*)
            FROM {qtable}
            WHERE {null_condition}
            """
        ).fetchone()[0]

        combinations = con.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT {group_cols}
                FROM {qtable}
                GROUP BY {group_cols}
            )
            """
        ).fetchone()[0]

        valid = (
            rows > 0
            and null_rows == 0
            and combinations == rows
        )

        return as_json(
            {
                "table": table,
                "columns": columns,
                "row_count": rows,
                "null_rows": null_rows,
                "distinct_combinations": combinations,
                "valid_composite_key": valid,
            }
        )

    finally:
        con.close()


# ------------------------------------------------------------
# INTERNAL FK CALCULATION
# ------------------------------------------------------------

def calculate_fk(
    con,
    source_table: str,
    source_column: str,
    target_table: str,
    target_column: str,
):
    validate_columns(
        con,
        source_table,
        [source_column],
    )

    validate_columns(
        con,
        target_table,
        [target_column],
    )

    source_type = get_columns(
        con,
        source_table,
    )[source_column]

    target_type = get_columns(
        con,
        target_table,
    )[target_column]

    qs_table = quote_identifier(source_table)
    qs_col = quote_identifier(source_column)
    qt_table = quote_identifier(target_table)
    qt_col = quote_identifier(target_column)

    (
        source_rows,
        source_nulls,
        source_distinct,
    ) = con.execute(
        f"""
        SELECT
            COUNT(*),
            COUNT(*) - COUNT({qs_col}),
            COUNT(DISTINCT {qs_col})
        FROM {qs_table}
        """
    ).fetchone()

    (
        target_rows,
        target_nulls,
        target_distinct,
    ) = con.execute(
        f"""
        SELECT
            COUNT(*),
            COUNT(*) - COUNT({qt_col}),
            COUNT(DISTINCT {qt_col})
        FROM {qt_table}
        """
    ).fetchone()

    (
        castable_values,
        matched_values,
    ) = con.execute(
        f"""
        WITH source_values AS (
            SELECT DISTINCT
                TRY_CAST({qs_col} AS {target_type}) AS value
            FROM {qs_table}
            WHERE {qs_col} IS NOT NULL
        ),
        target_values AS (
            SELECT DISTINCT
                {qt_col} AS value
            FROM {qt_table}
            WHERE {qt_col} IS NOT NULL
        )
        SELECT
            (
                SELECT COUNT(*)
                FROM source_values
                WHERE value IS NOT NULL
            ),
            (
                SELECT COUNT(*)
                FROM source_values s
                JOIN target_values t
                    ON s.value = t.value
                WHERE s.value IS NOT NULL
            )
        """
    ).fetchone()

    inclusion = (
        matched_values / castable_values
        if castable_values else 0
    )

    return {
        "source_table": source_table,
        "source_column": source_column,
        "target_table": target_table,
        "target_column": target_column,
        "source_type": source_type,
        "target_type": target_type,
        "type_compatible": compatible_types(
            source_type,
            target_type,
        ),
        "source_unique": (
            source_nulls == 0
            and source_distinct == source_rows
        ),
        "target_unique": (
            target_nulls == 0
            and target_distinct == target_rows
        ),
        "value_inclusion_ratio": inclusion,
        "matched_distinct_values": matched_values,
    }


# ------------------------------------------------------------
# TOOL 7 — TEST FOREIGN KEY
# ------------------------------------------------------------

@tool
def test_foreign_key(
    db_path: str,
    source_table: str,
    source_column: str,
    target_table: str,
    target_column: str,
) -> str:
    """
    Test whether one column plausibly references a key in another table.
    """

    con = connect_db(db_path)

    try:
        return as_json(
            calculate_fk(
                con,
                source_table,
                source_column,
                target_table,
                target_column,
            )
        )

    finally:
        con.close()


# ------------------------------------------------------------
# TOOL 8 — ANALYZE RELATIONSHIP
# ------------------------------------------------------------

@tool
def analyze_relationship(
    db_path: str,
    source_table: str,
    source_column: str,
    target_table: str,
    target_column: str,
) -> str:
    """
    Determine one-to-one or many-to-one relationship from FK evidence.
    """

    con = connect_db(db_path)

    try:
        evidence = calculate_fk(
            con,
            source_table,
            source_column,
            target_table,
            target_column,
        )

        if (
            evidence["target_unique"]
            and evidence[
                "value_inclusion_ratio"
            ] >= 0.90
        ):
            relation = (
                "one_to_one"
                if evidence["source_unique"]
                else "many_to_one"
            )
        else:
            relation = "uncertain"

        evidence["relationship"] = relation
        return as_json(evidence)

    finally:
        con.close()


# ============================================================
#
# SCHEMA AGENT TOOL SECTION ENDS HERE
#
# ============================================================


SCHEMA_TOOLS = [
    load_csv_files,
    clean_identifiers,
    inspect_schema,
    profile_columns,
    test_primary_key,
    test_composite_key,
    test_foreign_key,
    analyze_relationship,
]

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import gradio as gr
import plotly.graph_objects as go
from langchain_core.messages import HumanMessage

from config import (
    MAX_CSV_FILES,
    MAX_DASHBOARD_CHARTS,
    MAX_DASHBOARD_KPIS,
)
from llm import current_model_label
from utils import humanize_label
from workflow.edges import (
    ASK_GRAPH,
    DASHBOARD_GRAPH,
    SCHEMA_GRAPH,
)


# ============================================================
# APP HELPERS
# ============================================================

def _new_db_path() -> str:
    return str(
        Path(
            tempfile.gettempdir()
        )
        /
        f"vibebi_{uuid.uuid4().hex}.duckdb"
    )


def _normalize_file_list(
    files,
) -> list[str]:
    if files is None:
        return []

    if isinstance(
        files,
        (str, Path),
    ):
        return [str(files)]

    output = []

    for item in files:
        if isinstance(
            item,
            (str, Path),
        ):
            output.append(
                str(item)
            )

        elif hasattr(
            item,
            "name",
        ):
            output.append(
                str(item.name)
            )

        elif (
            isinstance(
                item,
                dict,
            )
            and item.get("path")
        ):
            output.append(
                str(item["path"])
            )

    return output


def clear_uploads():
    return []


def _schema_request(
    paths: list[str],
    db_path: str,
) -> str:
    return (
        "Discover the complete schema for "
        "these uploaded CSV files.\n\n"
        f"DATABASE PATH:\n{db_path}\n\n"
        "CSV FILES:\n"
        +
        "\n".join(
            str(
                Path(file).resolve()
            )
            for file in paths
        )
    )


def load_data(files):
    paths = _normalize_file_list(
        files
    )

    if not paths:
        raise gr.Error(
            "Upload at least one CSV file."
        )

    if len(paths) > MAX_CSV_FILES:
        raise gr.Error(
            f"Upload at most "
            f"{MAX_CSV_FILES} CSV files."
        )

    db_path = _new_db_path()

    try:
        result = SCHEMA_GRAPH.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=
                            _schema_request(
                                paths,
                                db_path,
                            )
                    )
                ],
                "csv_files":
                    paths,
                "db_path":
                    db_path,
            },
            config={
                "recursion_limit": 80
            },
        )

    except Exception as exc:
        raise gr.Error(
            f"Schema discovery failed: "
            f"{exc}"
        ) from exc

    schema_report = result.get(
        "schema_report",
        {},
    )

    if not schema_report:
        raise gr.Error(
            "Schema discovery did not "
            "produce a report."
        )

    status = (
        "✅ Data loaded and schema "
        f"discovered successfully using "
        f"`{current_model_label()}`."
    )

    schema_text = json.dumps(
        schema_report,
        indent=2,
        default=str,
    )

    return (
        db_path,
        schema_report,
        status,
        schema_text,
    )


# ============================================================
# ASK YOUR DATA
# ============================================================




def ask_data(
    db_path: str,
    schema_report,
    question: str,
):
    if not db_path:
        raise gr.Error(
            "Load CSV files first."
        )

    if not schema_report:
        raise gr.Error(
            "Schema report is missing."
        )

    if (
        not question
        or not question.strip()
    ):
        raise gr.Error(
            "Enter a question."
        )

    try:
        state = ASK_GRAPH.invoke(
            {
                "messages": [],
                "db_path":
                    db_path,
                "schema_report":
                    schema_report,
                "user_question":
                    question.strip(),
            },
            config={
                "recursion_limit":
                    35
            },
        )

    except Exception as exc:
        raise gr.Error(
            f"Analysis failed: {exc}"
        ) from exc

    answer_text = state.get(
        "answer",
        "",
    )

    sql_text = state.get(
        "sql_query",
        "",
    )

    result_df = state.get(
        "result_df",
    )

    return (
        answer_text,
        sql_text,
        result_df,
    )


# ============================================================
# DASHBOARD
# ============================================================

def build_dashboard(
    db_path: str,
    schema_report,
    instruction: str,
    kpi_count: int,
    chart_count: int,
):
    if not db_path:
        raise gr.Error(
            "Load CSV files first."
        )

    if not schema_report:
        raise gr.Error(
            "Schema report is missing."
        )

    instruction = (
        instruction or ""
    ).strip()

    if not instruction:
        instruction = (
            "Build a useful executive dashboard "
            "from the uploaded data."
        )

    kpi_count = max(
        0,
        min(
            int(kpi_count),
            MAX_DASHBOARD_KPIS,
        ),
    )

    chart_count = max(
        0,
        min(
            int(chart_count),
            MAX_DASHBOARD_CHARTS,
        ),
    )

    if (
        kpi_count == 0
        and chart_count == 0
    ):
        raise gr.Error(
            "Request at least one KPI "
            "or one chart."
        )

    try:
        state = DASHBOARD_GRAPH.invoke(
            {
                "messages": [],
                "db_path":
                    db_path,
                "schema_report":
                    schema_report,
                "dashboard_request":
                    instruction,
                "count_constraints": {
                    "kpis":
                        kpi_count,
                    "charts":
                        chart_count,
                },
                "dashboard_revision_count":
                    0,
            },
            config={
                "recursion_limit": 20
            },
        )

    except Exception as exc:
        raise gr.Error(
            "Dashboard generation failed: "
            f"{exc}"
        ) from exc

    results = state.get(
        "dashboard_results",
        {},
    )

    kpis = results.get(
        "kpis",
        [],
    )[:MAX_DASHBOARD_KPIS]

    charts = results.get(
        "charts",
        [],
    )[:MAX_DASHBOARD_CHARTS]

    plan = state.get(
        "dashboard_plan",
        {},
    )

    dashboard_title = (
        plan.get(
            "dashboard_title",
            "VibeBI Dashboard",
        )
        if isinstance(
            plan,
            dict,
        )
        else "VibeBI Dashboard"
    )

    dashboard_payload = [
        {
            "kind": "meta",
            "title":
                dashboard_title,
        },
        *kpis,
        *charts,
    ]

    plan_text = json.dumps(
        plan,
        indent=2,
        default=str,
    )

    final_text = json.dumps(
        state.get(
            "dashboard_final",
            {},
        ),
        indent=2,
        default=str,
    )

    errors_text = json.dumps(
        state.get(
            "dashboard_errors",
            [],
        ),
        indent=2,
        default=str,
    )

    return (
        dashboard_payload,
        plan_text,
        final_text,
        errors_text,
    )


# ============================================================
# DASHBOARD PRESENTATION EDITING
#
# Editing changes Plotly presentation only.
# SQL and dataframe logic are not changed.
# ============================================================

def _format_kpi(
    label: str,
    value,
    value_format: str = "number",
) -> str:
    if value is None:
        text = "—"

    elif (
        value_format == "currency"
        and isinstance(
            value,
            (int, float),
        )
    ):
        text = f"${value:,.2f}"

    elif (
        value_format == "percentage"
        and isinstance(
            value,
            (int, float),
        )
    ):
        text = f"{value:,.2f}%"

    elif isinstance(
        value,
        float,
    ):
        text = f"{value:,.2f}"

    elif isinstance(
        value,
        int,
    ):
        text = f"{value:,}"

    else:
        text = str(value)

    return (
        f"### {label}\n"
        f"# {text}"
    )


def _chart_editor_choices(
    items,
):
    charts = [
        item
        for item in (
            items or []
        )
        if item.get("kind")
        == "chart"
    ]

    choices = []

    for position, chart in enumerate(
        charts,
        start=1,
    ):
        spec = chart.get(
            "spec",
            {},
        )

        chart_id = chart.get(
            "id",
            f"chart_{position}",
        )

        title = (
            spec.get("title")
            or f"Chart {position}"
        )

        choices.append(
            (
                f"Chart {position}: "
                f"{title}",
                str(chart_id),
            )
        )

    return choices


def _find_chart(
    items,
    selected_chart,
):
    for item in (
        items or []
    ):
        if (
            item.get("kind")
            == "chart"
            and str(
                item.get("id")
            )
            == str(
                selected_chart
            )
        ):
            return item

    return None


def _selected_chart_editor_values(
    items,
    selected_chart,
):
    charts = [
        item
        for item in (
            items or []
        )
        if item.get("kind")
        == "chart"
    ]

    if not charts:
        raise gr.Error(
            "Build a dashboard with "
            "at least one chart first."
        )

    chart = _find_chart(
        items,
        selected_chart,
    )

    if chart is None:
        chart = charts[0]

    spec = chart.get(
        "spec",
        {},
    )

    kind = str(
        spec.get(
            "chart_type",
            "bar",
        )
    ).lower()

    title = (
        spec.get("title")
        or "Chart"
    )

    x_default = (
        spec.get("x_label")
        or humanize_label(
            spec.get("x")
        )
    )

    y_default = (
        spec.get("y_label")
        or (
            "Count"
            if kind == "histogram"
            else humanize_label(
                spec.get("y")
            )
        )
    )

    color_default = (
        spec.get("color_label")
        or humanize_label(
            spec.get("color")
        )
    )

    return (
        title,
        x_default,
        y_default,
        color_default,
    )


def open_dashboard_chart_editor(
    items,
):
    choices = _chart_editor_choices(
        items
    )

    if not choices:
        raise gr.Error(
            "Build a dashboard with "
            "at least one chart first."
        )

    selected = choices[0][1]

    (
        title,
        x_label,
        y_label,
        color_label,
    ) = (
        _selected_chart_editor_values(
            items,
            selected,
        )
    )

    return (
        gr.update(
            choices=choices,
            value=selected,
        ),
        title,
        x_label,
        y_label,
        color_label,
        gr.update(
            visible=True
        ),
    )


def load_dashboard_chart_editor(
    items,
    selected_chart,
):
    return (
        _selected_chart_editor_values(
            items,
            selected_chart,
        )
    )


def apply_dashboard_chart_editor(
    items,
    selected_chart,
    title,
    x_label,
    y_label,
    color_label,
):
    if not selected_chart:
        raise gr.Error(
            "Choose a chart to edit."
        )

    updated = list(
        items or []
    )

    found = False

    for pos, item in enumerate(
        updated
    ):
        if (
            item.get("kind")
            != "chart"
            or str(
                item.get("id")
            )
            != str(
                selected_chart
            )
        ):
            continue

        new_item = dict(item)
        spec = dict(
            new_item.get(
                "spec",
                {},
            )
        )

        spec["title"] = (
            (title or "").strip()
            or spec.get("title")
            or "Chart"
        )

        spec["x_label"] = (
            (x_label or "").strip()
            or None
        )

        spec["y_label"] = (
            (y_label or "").strip()
            or None
        )

        spec["color_label"] = (
            (color_label or "").strip()
            or None
        )

        figure = go.Figure(
            new_item[
                "figure_json"
            ]
        )

        figure.update_layout(
            title=spec["title"],
            xaxis_title=spec[
                "x_label"
            ],
            yaxis_title=spec[
                "y_label"
            ],
            legend_title_text=spec[
                "color_label"
            ],
        )

        new_item["spec"] = spec
        new_item[
            "figure_json"
        ] = figure.to_dict()

        updated[pos] = new_item
        found = True
        break

    if not found:
        raise gr.Error(
            "That chart is no longer "
            "available."
        )

    return (
        updated,
        gr.update(
            choices=
                _chart_editor_choices(
                    updated
                ),
            value=
                str(
                    selected_chart
                ),
        ),
    )


# ============================================================
# UI STYLE
# ============================================================

CSS = """
.gradio-container {
  --vibebi-bg: #120928;
  --vibebi-bg-deep: #0f071f;
  --vibebi-panel: #342a4d;
  --vibebi-panel-alt: #2c254a;
  --vibebi-panel-hover: #40355b;
  --vibebi-input: #211737;
  --vibebi-border: #6c6c97;
  --vibebi-accent: #727cc0;
  --vibebi-accent-strong: #8790d6;
  --vibebi-text: #ffffff;
  --vibebi-muted: #ffffff;

  background: var(--vibebi-bg) !important;
  color: var(--vibebi-text) !important;
  min-height: 100vh;

  /* Override Gradio theme surfaces so white panels do not appear. */
  --body-background-fill: var(--vibebi-bg) !important;
  --body-text-color: var(--vibebi-text) !important;
  --background-fill-primary: var(--vibebi-panel) !important;
  --background-fill-secondary: var(--vibebi-panel) !important;
  --border-color-primary: var(--vibebi-border) !important;
  --border-color-accent: var(--vibebi-accent) !important;

  --block-background-fill: var(--vibebi-panel) !important;
  --block-border-color: var(--vibebi-border) !important;
  --block-label-background-fill: var(--vibebi-panel) !important;
  --block-label-text-color: var(--vibebi-text) !important;
  --block-title-text-color: var(--vibebi-text) !important;

  --input-background-fill: var(--vibebi-input) !important;
  --input-border-color: var(--vibebi-border) !important;
  --input-placeholder-color: #b8b5c8 !important;

  --button-primary-background-fill: var(--vibebi-accent) !important;
  --button-primary-background-fill-hover: var(--vibebi-accent-strong) !important;
  --button-primary-text-color: #ffffff !important;

  --button-secondary-background-fill: var(--vibebi-accent) !important;
  --button-secondary-background-fill-hover: var(--vibebi-accent-strong) !important;
  --button-secondary-text-color: #ffffff !important;
  --button-secondary-border-color: #9098db !important;

  --link-text-color: #ffffff !important;
  --link-text-color-hover: #ffffff !important;
}

html,
body {
  background: var(--vibebi-bg, #120928) !important;
  color: #ffffff !important;
}

/* ==========================================================
   GLOBAL TEXT
   ========================================================== */

.gradio-container,
.gradio-container p,
.gradio-container span,
.gradio-container label,
.gradio-container h1,
.gradio-container h2,
.gradio-container h3,
.gradio-container h4,
.gradio-container h5,
.gradio-container h6,
.gradio-container .prose,
.gradio-container .prose *,
.gradio-container summary {
  color: #ffffff !important;
}

#app-title,
#app-title *,
#ask-answer,
#ask-answer *,
.dashboard-title,
.dashboard-title *,
.kpi-card,
.kpi-card * {
  color: #ffffff !important;
}

#app-title {
  text-align: center;
  margin: 0;
  padding: 0.9rem 1rem 0.3rem;
  font-weight: 800;
  letter-spacing: 0.02em;
}

/* ==========================================================
   TABS — DATA / ASK YOUR DATA / AUTO DASHBOARD
   ========================================================== */

.gradio-container .tab-nav,
.gradio-container [role="tablist"] {
  background: #1c1433 !important;
  border: 1px solid #4a4367 !important;
  border-radius: 12px !important;
  padding: 5px !important;
  gap: 4px !important;
}

.gradio-container button[role="tab"] {
  color: #ffffff !important;
  background: transparent !important;
  border: 0 !important;
  border-radius: 9px !important;
  font-weight: 700 !important;
}

.gradio-container button[role="tab"] * {
  color: #ffffff !important;
}

.gradio-container button[role="tab"][aria-selected="true"] {
  color: #ffffff !important;
  background: var(--vibebi-panel) !important;
  box-shadow: inset 0 0 0 1px #5f5d82 !important;
}

/* ==========================================================
   REMOVE WHITE GRADIO SURFACES
   ========================================================== */

.gradio-container .block,
.gradio-container .panel,
.gradio-container .form,
.gradio-container .wrap,
.gradio-container fieldset,
.gradio-container details,
.gradio-container .accordion,
.gradio-container [data-testid="file"],
.gradio-container [data-testid="upload-button"],
.gradio-container .file-preview {
  background: var(--vibebi-panel) !important;
  color: #ffffff !important;
  border-color: var(--vibebi-border) !important;
}

/* Inputs stay darker than the KPI/panel surface. */
.gradio-container textarea,
.gradio-container input,
.gradio-container select {
  background: var(--vibebi-input) !important;
  color: #ffffff !important;
  border-color: var(--vibebi-border) !important;
}

.gradio-container textarea::placeholder,
.gradio-container input::placeholder {
  color: #b8b5c8 !important;
}

/* Dropdowns and menus */
.gradio-container [role="listbox"],
.gradio-container [role="option"],
.gradio-container ul.options,
.gradio-container .options {
  background: var(--vibebi-input) !important;
  color: #ffffff !important;
  border-color: var(--vibebi-border) !important;
}

.gradio-container [role="option"]:hover,
.gradio-container [role="option"][aria-selected="true"] {
  background: var(--vibebi-panel-hover) !important;
  color: #ffffff !important;
}

/* Tables / code / accordions */
.gradio-container table,
.gradio-container thead,
.gradio-container tbody,
.gradio-container tr,
.gradio-container th,
.gradio-container td {
  background: var(--vibebi-panel) !important;
  color: #ffffff !important;
  border-color: #5f5d82 !important;
}

.gradio-container pre,
.gradio-container code {
  background: #18102d !important;
  color: #ffffff !important;
  border-color: #4a4367 !important;
}

.gradio-container details,
.gradio-container summary {
  background: var(--vibebi-panel) !important;
  color: #ffffff !important;
}

/* ==========================================================
   BUTTONS
   ========================================================== */

.gradio-container button.primary,
.gradio-container button.secondary {
  background: var(--vibebi-accent) !important;
  color: #ffffff !important;
  border-color: #9098db !important;
}

.gradio-container button.primary:hover,
.gradio-container button.secondary:hover {
  background: var(--vibebi-accent-strong) !important;
}

.gradio-container button:not([role="tab"]) {
  color: #ffffff !important;
}

/* ==========================================================
   DASHBOARD
   ========================================================== */

#dashboard-export-area {
  background: var(--vibebi-bg) !important;
  color: #ffffff !important;
  padding: 14px !important;
  border: 1px solid #2e2a4f !important;
  border-radius: 14px !important;
}

.dashboard-title,
.dashboard-title * {
  color: #ffffff !important;
  font-weight: 800 !important;
}

.kpi-card {
  background: var(--vibebi-panel) !important;
  color: #ffffff !important;
  border: 1px solid #5f5d82 !important;
  border-radius: 12px !important;
  padding: 12px 14px !important;
  min-height: 120px;
  box-shadow: none !important;
  overflow: visible !important;
  scrollbar-color: #6c6c97 var(--vibebi-panel) !important;
}

.kpi-card > div,
.kpi-card .block,
.kpi-card .wrap,
.kpi-card .prose {
  background: var(--vibebi-panel) !important;
  overflow: visible !important;
  max-height: none !important;
}

.kpi-card ::-webkit-scrollbar {
  width: 8px;
  background: var(--vibebi-panel);
}

.kpi-card ::-webkit-scrollbar-track {
  background: var(--vibebi-panel);
}

.kpi-card ::-webkit-scrollbar-thumb {
  background: #6c6c97;
  border-radius: 999px;
  border: 2px solid var(--vibebi-panel);
}

.kpi-card h3 {
  color: #ffffff !important;
  margin-bottom: 0.45rem !important;
  font-size: 1rem !important;
  font-weight: 700 !important;
}

.kpi-card h1 {
  color: #ffffff !important;
  font-size: 2rem !important;
  line-height: 1.05 !important;
  margin: 0 !important;
}

.dashboard-chart {
  background: var(--vibebi-panel) !important;
  border: 1px solid #5f5d82 !important;
  border-radius: 12px !important;
  overflow: hidden !important;
  box-shadow: none !important;
}

.dashboard-chart [data-testid="block-label"] {
  color: #ffffff !important;
}

/* ==========================================================
   CHART EDITOR
   Fixes the white area shown in the screenshot.
   ========================================================== */

.chart-edit-panel,
.chart-edit-panel > div,
.chart-edit-panel .block,
.chart-edit-panel .panel,
.chart-edit-panel .form,
.chart-edit-panel .wrap,
.chart-edit-panel fieldset {
  background: var(--vibebi-panel) !important;
  color: #ffffff !important;
  border-color: #5f5d82 !important;
}

.chart-edit-panel {
  width: 100% !important;
  margin-top: 8px !important;
  padding: 12px !important;
  border: 1px solid #5f5d82 !important;
  border-radius: 12px !important;
  box-shadow: none !important;
}

.chart-edit-panel textarea,
.chart-edit-panel input,
.chart-edit-panel select {
  background: var(--vibebi-input) !important;
  color: #ffffff !important;
  border-color: #7775a3 !important;
}

.chart-edit-panel label,
.chart-edit-panel span,
.chart-edit-panel p {
  color: #ffffff !important;
}

.dashboard-action-row .dashboard-action-button {
  width: 100% !important;
  min-width: 0 !important;
  max-width: none !important;
  flex: 1 1 0 !important;
}




/* ==========================================================
   PRINT
   ========================================================== */

.print-chart-img {
  display: none !important;
}

@media print {

  @page {
    size: A4 landscape;
    margin: 4mm;
  }

  html,
  body {
    margin: 0 !important;
    padding: 0 !important;

    background: #120928 !important;
    color: #ffffff !important;

    overflow: visible !important;

    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }


  /* Hide everything outside the dashboard. */
  body.printing-dashboard * {
    visibility: hidden !important;
  }


  /* Show only the dashboard export area. */
  body.printing-dashboard #dashboard-export-area,
  body.printing-dashboard #dashboard-export-area * {
    visibility: visible !important;
  }


  body.printing-dashboard #dashboard-export-area {

    position: absolute !important;

    left: 0 !important;
    top: 0 !important;

    margin: 0 !important;
    padding: 6px !important;

    border: 0 !important;
    border-radius: 0 !important;

    background: #120928 !important;

    /*
     * Keep the original dashboard width.
     * JavaScript supplies both values.
     */
    width:
      var(
        --dashboard-print-width
      ) !important;

    max-width: none !important;

    /*
     * Shrink the complete dashboard uniformly
     * until it fits on one A4 landscape page.
     */
    zoom:
      var(
        --dashboard-print-scale,
        1
      ) !important;

    overflow: visible !important;

    break-inside: avoid !important;
    page-break-inside: avoid !important;
  }


  /*
   * The user requested KPI + charts only.
   * Do not print the dashboard heading.
   */
  body.printing-dashboard
  #dashboard-export-area
  .dashboard-title {

    display: none !important;
  }


  /*
   * VERY IMPORTANT:
   *
   * Keep every Gradio Row as one row.
   *
   * Therefore:
   *   4 KPI -> 4 KPI on the same line
   *   3 KPI -> 3 KPI on the same line
   *
   * Charts continue to use the rows created
   * by the Python code:
   *   chart 1 | chart 2
   *   chart 3 | chart 4
   */
  body.printing-dashboard
  #dashboard-export-area
  .row {

    display: flex !important;

    flex-direction: row !important;

    flex-wrap: nowrap !important;

    align-items: stretch !important;

    width: 100% !important;

    gap: 8px !important;

    margin: 0 0 8px 0 !important;

    break-inside: avoid !important;
    page-break-inside: avoid !important;
  }


  /*
   * Columns share the row width equally.
   *
   * This stops Gradio's responsive print CSS
   * from placing cards underneath one another.
   */
  body.printing-dashboard
  #dashboard-export-area
  .row > .column {

    flex: 1 1 0 !important;

    width: auto !important;

    min-width: 0 !important;

    max-width: none !important;

    break-inside: avoid !important;
    page-break-inside: avoid !important;
  }


  /* -----------------------------
     KPI cards
     ----------------------------- */

  body.printing-dashboard
  #dashboard-export-area
  .kpi-card {

    min-height: 0 !important;

    height: auto !important;

    padding: 8px 10px !important;

    margin: 0 !important;

    background: #342a4d !important;

    border: 1px solid #5f5d82 !important;

    border-radius: 10px !important;

    overflow: visible !important;

    break-inside: avoid !important;
    page-break-inside: avoid !important;
  }


  body.printing-dashboard
  #dashboard-export-area
  .kpi-card h1 {

    font-size: 1.55rem !important;
    line-height: 1.05 !important;
    margin: 0 !important;
  }


  body.printing-dashboard
  #dashboard-export-area
  .kpi-card h3 {

    font-size: 0.85rem !important;

    margin:
      0 0 4px 0 !important;
  }


  /* -----------------------------
     Charts
     ----------------------------- */

  /*
   * Hide interactive Plotly.
   * JavaScript creates an SVG image for PDF.
   */
  body.printing-dashboard
  #dashboard-export-area
  .js-plotly-plot {

    display: none !important;
  }


  body.printing-dashboard
  #dashboard-export-area
  .dashboard-chart {

    width: 100% !important;

    height: auto !important;

    min-height: 0 !important;

    margin: 0 !important;

    padding: 0 !important;

    background: #342a4d !important;

    border-radius: 10px !important;

    overflow: hidden !important;

    break-inside: avoid !important;
    page-break-inside: avoid !important;
  }


  body.printing-dashboard
  #dashboard-export-area
  .print-chart-img {

    display: block !important;

    width: 100% !important;

    height: auto !important;

    max-width: 100% !important;

    object-fit: contain !important;

    margin: 0 !important;

    border-radius: 10px !important;
  }


  /* Never print controls/edit areas. */
  body.printing-dashboard .no-pdf {

    display: none !important;
  }
}
"""





PDF_DOWNLOAD_JS = r"""
async () => {

  const source =
    document.querySelector(
      '#dashboard-export-area'
    );

  if (
    !source
    || !source.innerText.trim()
  ) {
    alert(
      'Build a dashboard before printing.'
    );

    return [];
  }


  const body =
    document.body;

  const previousTitle =
    document.title;


  /*
   * Remember the original inline
   * properties so they can be restored.
   */
  const cleanup = () => {

    document
      .querySelectorAll(
        '.print-chart-img'
      )
      .forEach(
        (element) =>
          element.remove()
      );


    body.classList.remove(
      'printing-dashboard'
    );


    source.style.removeProperty(
      '--dashboard-print-scale'
    );


    source.style.removeProperty(
      '--dashboard-print-width'
    );


    document.title =
      previousTitle;
  };


  /*
   * Remove anything left from a
   * previous print operation.
   */
  cleanup();


  /*
   * Use dashboard name for the
   * generated PDF filename.
   *
   * The heading itself will not
   * be visible in the PDF.
   */
  const dashboardHeading =
    source.querySelector(
      '.dashboard-title'
    );


  document.title =
    (
      dashboardHeading
      && dashboardHeading
          .innerText
          .trim()
    )
    || 'VibeBI Dashboard';


  /*
   * -----------------------------------
   * Convert Plotly charts to SVG images
   * -----------------------------------
   *
   * Printing Plotly's interactive DOM
   * directly can cause clipping or
   * incorrect resizing.
   *
   * SVG preserves text and graphics
   * sharply in the PDF.
   */
  const chartImages = [];


  if (window.Plotly) {

    const plots =
      source.querySelectorAll(
        '.js-plotly-plot'
      );


    for (const gd of plots) {

      try {

        const rect =
          gd.getBoundingClientRect();


        /*
         * Preserve the actual chart's
         * on-screen aspect ratio.
         */
        const width =
          Math.max(
            450,
            Math.round(
              rect.width || 800
            )
          );


        const height =
          Math.max(
            280,
            Math.round(
              rect.height || 450
            )
          );


        const url =
          await window.Plotly.toImage(
            gd,
            {
              format: 'svg',
              width: width,
              height: height
            }
          );


        const img =
          document.createElement(
            'img'
          );


        img.src =
          url;


        img.className =
          'print-chart-img';


        img.style.aspectRatio =
          `${width} / ${height}`;


        /*
         * Put the printable SVG directly
         * after the interactive Plotly chart.
         */
        gd.insertAdjacentElement(
          'afterend',
          img
        );


        chartImages.push(
          img
        );

      }
      catch (error) {

        console.error(
          'Could not prepare chart for PDF:',
          error
        );

      }

    }

  }


  /*
   * Wait until every generated SVG image
   * is ready.
   */
  await Promise.all(

    chartImages.map(

      (img) =>
        new Promise(
          (resolve) => {

            if (img.complete) {

              resolve();

              return;

            }


            img.addEventListener(
              'load',
              resolve,
              {
                once: true
              }
            );


            img.addEventListener(
              'error',
              resolve,
              {
                once: true
              }
            );

          }
        )

    )

  );


  /*
   * Also wait for fonts.
   */
  if (
    document.fonts
    && document.fonts.ready
  ) {

    await document.fonts.ready;

  }


  await new Promise(

    (resolve) =>
      requestAnimationFrame(

        () =>
          requestAnimationFrame(
            resolve
          )

      )

  );


  /*
   * -----------------------------------
   * Preserve original dashboard width
   * -----------------------------------
   *
   * This is important.
   *
   * The PDF should shrink the dashboard,
   * not reorganize its rows.
   */
  const rect =
    source.getBoundingClientRect();


  const dashboardWidth =
    Math.max(
      source.scrollWidth,
      rect.width,
      1
    );


  const dashboardHeight =
    Math.max(
      source.scrollHeight,
      rect.height,
      1
    );


  /*
   * Fix the print width to the width used
   * when the dashboard was displayed.
   */
  source.style.setProperty(
    '--dashboard-print-width',
    `${dashboardWidth}px`
  );


  /*
   * -----------------------------------
   * A4 LANDSCAPE ONE-PAGE SIZE
   * -----------------------------------
   *
   * A4 landscape is approximately:
   *
   * 1123 x 794 CSS px at 96 dpi.
   *
   * After margins and a safety allowance,
   * these values keep the dashboard on
   * one page.
   */
  const targetWidth =
    1080;


  const targetHeight =
    745;


  /*
   * Calculate one scale factor for the
   * WHOLE dashboard.
   *
   * Do not independently resize cards.
   */
  let printScale =
    Math.min(
      1,
      targetWidth /
        dashboardWidth,
      targetHeight /
        dashboardHeight
    );


  /*
   * Small safety factor because Chrome/
   * Chromium print calculations can differ
   * slightly from normal screen layout.
   */
  printScale =
    printScale * 0.95;


  /*
   * Avoid an invalid/zero zoom.
   */
  printScale =
    Math.max(
      0.05,
      printScale
    );


  source.style.setProperty(
    '--dashboard-print-scale',
    String(
      printScale
    )
  );


  /*
   * Turn on print-only CSS.
   */
  body.classList.add(
    'printing-dashboard'
  );


  await new Promise(

    (resolve) =>
      requestAnimationFrame(

        () =>
          requestAnimationFrame(
            resolve
          )

      )

  );


  /*
   * Restore the normal dashboard after
   * the browser print dialog closes.
   */
  window.addEventListener(
    'afterprint',
    cleanup,
    {
      once: true
    }
  );


  window.print();


  return [];
}
"""


# ============================================================
# GRADIO UI
# ============================================================

with gr.Blocks(
    title="VibeBI",
) as demo:

    gr.HTML(
        f"<style>{CSS}</style>"
    )
    gr.Markdown(
        "# VibeBI",
        elem_id="app-title",
        elem_classes=[
            "no-pdf"
        ],
    )

    db_state = gr.State("")
    schema_state = gr.State({})

    with gr.Tab("Data"):
        csv_files = gr.Files(
            label="Upload CSV files",
            file_types=[
                ".csv"
            ],
            type="filepath",
        )

        with gr.Row():
            load_button = gr.Button(
                "Load data",
                variant="primary",
            )

            clear_button = gr.Button(
                "Clear selected files",
                variant="secondary",
            )

        load_status = gr.Markdown()

        with gr.Accordion(
            "Discovered schema",
            open=False,
        ):
            schema_box = gr.Code(
                language="json",
                label="Schema report",
            )

    with gr.Tab("Ask your data"):
        question = gr.Textbox(
            label="Question",
            placeholder=(
                "Example: Which customer "
                "segment generated the "
                "highest total sales?"
            ),
            lines=2,
        )

        ask_button = gr.Button(
            "Analyze",
            variant="primary",
        )

        answer = gr.Markdown(
            elem_id="ask-answer",
        )

        with gr.Accordion(
                "Generated SQL",
                open=False,
        ):
            sql_box = gr.Code(
                language="sql",
                label="SQL",
            )

        result_table = gr.Dataframe(
            label="SQL Result",
            interactive=False,
            type="pandas",
            wrap=True,
        )


    with gr.Tab("Auto dashboard"):
        dashboard_instruction = gr.Textbox(
            label="Dashboard request",
            value=(
                "Build a useful executive "
                "dashboard from the uploaded "
                "data."
            ),
            lines=3,
            elem_classes=[
                "no-pdf"
            ],
        )

        with gr.Row(
            elem_classes=[
                "no-pdf"
            ]
        ):
            kpi_count = gr.Number(
                label="Number of KPIs",
                value=2,
                minimum=0,
                maximum=
                    MAX_DASHBOARD_KPIS,
                precision=0,
            )

            chart_count = gr.Number(
                label="Number of charts",
                value=2,
                minimum=0,
                maximum=
                    MAX_DASHBOARD_CHARTS,
                precision=0,
            )

        dashboard_button = gr.Button(
            "Build dashboard",
            variant="primary",
            elem_classes=[
                "no-pdf"
            ],
        )

        dashboard_state = gr.State(
            []
        )

        with gr.Column(
            elem_id=
                "dashboard-export-area"
        ):

            @gr.render(
                inputs=
                    dashboard_state,
                triggers=[
                    dashboard_state.change
                ],
                show_progress=
                    "hidden",
            )
            def render_dashboard_panels(
                items
            ):
                items = items or []

                meta = next(
                    (
                        item
                        for item in items
                        if item.get("kind")
                        == "meta"
                    ),
                    {},
                )

                kpis = [
                    item
                    for item in items
                    if item.get("kind")
                    == "kpi"
                ]

                charts = [
                    item
                    for item in items
                    if item.get("kind")
                    == "chart"
                ]

                if kpis or charts:
                    gr.Markdown(
                        "## "
                        + meta.get(
                            "title",
                            "VibeBI Dashboard",
                        ),
                        elem_classes=[
                            "dashboard-title"
                        ],
                    )

                if kpis:
                    with gr.Row():
                        for i, kpi in enumerate(
                            kpis
                        ):
                            with gr.Column(
                                elem_classes=[
                                    "kpi-card"
                                ],
                                key=
                                    f"kpi-col-{i}",
                            ):
                                gr.Markdown(
                                    _format_kpi(
                                        kpi.get(
                                            "label",
                                            f"KPI {i+1}",
                                        ),
                                        kpi.get(
                                            "value"
                                        ),
                                        kpi.get(
                                            "format",
                                            "number",
                                        ),
                                    ),
                                    key=
                                        f"kpi-{i}",
                                )

                for row_start in range(
                    0,
                    len(charts),
                    2,
                ):
                    row_charts = charts[
                        row_start:
                        row_start + 2
                    ]

                    with gr.Row(
                        key=
                            f"chart-row-"
                            f"{row_start // 2}"
                    ):
                        for offset, chart in (
                            enumerate(
                                row_charts
                            )
                        ):
                            idx = (
                                row_start
                                + offset
                            )

                            figure = go.Figure(
                                chart[
                                    "figure_json"
                                ]
                            )

                            with gr.Column(
                                key=
                                    f"chart-col-{idx}"
                            ):
                                gr.Plot(
                                    value=
                                        figure,
                                    show_label=
                                        False,
                                    elem_classes=[
                                        "dashboard-chart"
                                    ],
                                    key=
                                        f"chart-{idx}",
                                )

        with gr.Row(
            elem_classes=[
                "no-pdf",
                "dashboard-action-row",
            ]
        ):
            edit_dashboard_button = (
                gr.Button(
                    "Edit chart",
                    variant="secondary",
                    elem_classes=[
                        "dashboard-action-button"
                    ],
                )
            )

            export_pdf_button = (
                gr.Button(
                    "Save dashboard as PDF",
                    variant="secondary",
                    elem_classes=[
                        "dashboard-action-button"
                    ],
                )
            )

        with gr.Column(
            visible=False,
            elem_classes=[
                "no-pdf",
                "chart-edit-panel",
            ],
        ) as global_chart_editor:

            chart_selector = (
                gr.Dropdown(
                    label=
                        "Chart to edit",
                    choices=[],
                    interactive=True,
                )
            )

            chart_title_box = (
                gr.Textbox(
                    label=
                        "Chart title"
                )
            )

            chart_x_label_box = (
                gr.Textbox(
                    label=
                        "X-axis / "
                        "category / "
                        "location label"
                )
            )

            chart_y_label_box = (
                gr.Textbox(
                    label=
                        "Y-axis / value "
                        "label"
                )
            )

            chart_color_label_box = (
                gr.Textbox(
                    label=
                        "Legend label "
                        "(optional)"
                )
            )

            with gr.Row():
                apply_chart_changes = (
                    gr.Button(
                        "Apply changes",
                        size="sm",
                    )
                )

                close_chart_editor = (
                    gr.Button(
                        "Close",
                        size="sm",
                    )
                )

        with gr.Accordion(
            "Dashboard plan",
            open=False,
            elem_classes=[
                "no-pdf"
            ],
        ):
            dashboard_plan_box = gr.Code(
                language="json",
                label="Plan",
            )

        with gr.Accordion(
            "Dashboard final status",
            open=False,
            elem_classes=[
                "no-pdf"
            ],
        ):
            dashboard_final_box = gr.Code(
                language="json",
                label="Final",
            )

        with gr.Accordion(
            "Remaining errors",
            open=False,
            elem_classes=[
                "no-pdf"
            ],
        ):
            dashboard_errors_box = gr.Code(
                language="json",
                label="Errors",
            )


    # ========================================================
    # GRADIO EVENTS
    # ========================================================

    clear_button.click(
        clear_uploads,
        outputs=[
            csv_files
        ],
    )

    load_button.click(
        load_data,
        inputs=[
            csv_files
        ],
        outputs=[
            db_state,
            schema_state,
            load_status,
            schema_box,
        ],
    )

    ask_button.click(
        ask_data,
        inputs=[
            db_state,
            schema_state,
            question,
        ],
        outputs=[
            answer,
            sql_box,
            result_table,
        ],
    )


    dashboard_run = (
        dashboard_button.click(
            build_dashboard,
            inputs=[
                db_state,
                schema_state,
                dashboard_instruction,
                kpi_count,
                chart_count,
            ],
            outputs=[
                dashboard_state,
                dashboard_plan_box,
                dashboard_final_box,
                dashboard_errors_box,
            ],
        )
    )

    dashboard_run.then(
        fn=lambda:
            gr.update(
                visible=False
            ),
        outputs=[
            global_chart_editor
        ],
        queue=False,
    )

    edit_dashboard_button.click(
        open_dashboard_chart_editor,
        inputs=[
            dashboard_state
        ],
        outputs=[
            chart_selector,
            chart_title_box,
            chart_x_label_box,
            chart_y_label_box,
            chart_color_label_box,
            global_chart_editor,
        ],
        queue=False,
    )

    chart_selector.change(
        load_dashboard_chart_editor,
        inputs=[
            dashboard_state,
            chart_selector,
        ],
        outputs=[
            chart_title_box,
            chart_x_label_box,
            chart_y_label_box,
            chart_color_label_box,
        ],
        queue=False,
    )

    apply_chart_changes.click(
        apply_dashboard_chart_editor,
        inputs=[
            dashboard_state,
            chart_selector,
            chart_title_box,
            chart_x_label_box,
            chart_y_label_box,
            chart_color_label_box,
        ],
        outputs=[
            dashboard_state,
            chart_selector,
        ],
    )

    close_chart_editor.click(
        fn=lambda:
            gr.update(
                visible=False
            ),
        outputs=[
            global_chart_editor
        ],
        queue=False,
    )

    export_pdf_button.click(
        fn=None,
        js=PDF_DOWNLOAD_JS,
        queue=False,
    )


if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
    )
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# HUGGING FACE MODEL CONFIGURATION
# ============================================================
#
# The project uses the Hugging Face OpenAI-compatible router.
# No OpenAI API key is required.
#
# Put your real Hugging Face token in .env:
#
# HF_TOKEN=hf_...
#
# You can change HF_MODEL in .env without changing Python code.
# ============================================================

HF_TOKEN = (
    os.getenv("HF_TOKEN")
    or os.getenv("HUGGINGFACEHUB_API_TOKEN")
)

if not HF_TOKEN:
    raise RuntimeError(
        "Missing Hugging Face token. "
        "Create a .env file and set HF_TOKEN=hf_..."
    )

HF_MODEL = os.getenv(
    "HF_MODEL",
    "openai/gpt-oss-120b:fastest",
)

HF_BASE_URL = os.getenv(
    "HF_BASE_URL",
    "https://router.huggingface.co/v1",
)

PORT = int(
    os.getenv(
        "PORT",
        "7860",
    )
)

MAX_CSV_FILES = int(
    os.getenv(
        "MAX_CSV_FILES",
        "10",
    )
)

MAX_DASHBOARD_KPIS = int(
    os.getenv(
        "MAX_DASHBOARD_KPIS",
        "6",
    )
)

MAX_DASHBOARD_CHARTS = int(
    os.getenv(
        "MAX_DASHBOARD_CHARTS",
        "6",
    )
)

MAX_DASHBOARD_REVISIONS = int(
    os.getenv(
        "MAX_DASHBOARD_REVISIONS",
        "2",
    )
)

from __future__ import annotations

from langchain_openai import ChatOpenAI

from config import (
    HF_BASE_URL,
    HF_MODEL,
    HF_TOKEN,
)


# ============================================================
# HUGGING FACE LLM
#
# ChatOpenAI is used only as the client for Hugging Face's
# OpenAI-compatible router endpoint.
#
# Requests go to:
# https://router.huggingface.co/v1
#
# Authentication uses:
# HF_TOKEN
# ============================================================

llm = ChatOpenAI(
    model=HF_MODEL,
    api_key=HF_TOKEN,
    base_url=HF_BASE_URL,
    temperature=0,
)


def current_model_label() -> str:
    return (
        "Hugging Face · "
        f"{HF_MODEL}"
    )

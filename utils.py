from __future__ import annotations

import json
import re
from typing import Any


def as_json(data: Any) -> str:
    return json.dumps(
        data,
        indent=2,
        default=str,
    )


def extract_json(text: str):
    text = (text or "").strip()

    text = re.sub(
        r"^```(?:json)?",
        "",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"```$",
        "",
        text,
    ).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def humanize_label(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).replace("_", " ").strip()
    return text[:1].upper() + text[1:]

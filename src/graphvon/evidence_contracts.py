"""Identity and validation helpers for retained evidence reports."""

from __future__ import annotations

import re
from typing import Any

from .contracts import Refusal, content_digest


def root(value: Any) -> dict:
    """Validate only the envelope; independent records are checked later."""
    keys = {"version", "scope", "upstream", "change", "selections", "observations",
            "correspondence", "claim", "joint_assessment", "decision"}
    if not isinstance(value, dict) or set(value) != keys or type(value["version"]) is not int or value["version"] != 1:
        raise Refusal("Invalid report envelope.")
    if not isinstance(value["scope"], str) or not value["scope"].strip():
        raise Refusal("Invalid report scope.")
    for name in ("upstream", "change", "correspondence", "claim"):
        if not isinstance(value[name], dict):
            raise Refusal("Invalid report component.")
    for name in ("selections", "observations"):
        if not isinstance(value[name], list):
            raise Refusal("Invalid report collection.")
    return value


def fields(value: Any, required: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != required:
        raise Refusal("Invalid record fields.")
    return value


def string(value: Any, *, empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value or (not empty and not value.strip()):
        raise Refusal("Invalid text.")
    return value


def strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise Refusal("Invalid text list.")
    return [string(x) for x in value]


def assessment(value: Any, subject: str | None) -> dict:
    if value is None:
        return {"status": "not_assessed", "subject": subject}
    try:
        fields(value, {"subject", "result", "provenance", "reasons", "limits"})
        if not re.fullmatch(r"[0-9a-f]{64}", string(value["subject"])):
            raise Refusal("Invalid subject.")
        if not isinstance(value["result"], str) or value["result"] not in {"supported", "discrepancy", "unknown"}:
            raise Refusal("Invalid result.")
        string(value["provenance"]); strings(value["reasons"]); strings(value["limits"])
    except Refusal:
        return {"status": "invalid", "subject": subject, "declared": value}
    status = "unavailable" if subject is None else ("applicable" if value["subject"] == subject else "stale")
    return {"status": status, "subject": subject, "declared": value}


def identity(domain: str, value: Any) -> str:
    return content_digest({"domain": domain, "value": value})

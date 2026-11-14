"""Two-pass, GET-only observations of the selected native Issue and Draft."""

from __future__ import annotations

import re

from .contracts import Refusal
from .issue_check import SourceReader
from .issue_contracts import text
from .sources import _discussion


def _one(reader: SourceReader, issue: dict, pr: dict | None) -> dict:
    prefix = "repos/" + reader.project.repository
    repo = reader._get(prefix)
    if (not isinstance(repo, dict) or repo.get("node_id") != reader.project.repository_id
            or str(repo.get("full_name", "")).casefold() != reader.project.repository
            or type(repo.get("id")) is not int or repo["id"] <= 0):
        raise Refusal("Native repository identity differs.")
    number = issue["number"]
    native = reader._get(f"{prefix}/issues/{number}")
    if (not isinstance(native, dict) or "pull_request" in native or native.get("number") != number
            or native.get("node_id") != issue["node_id"] or type(native.get("id")) is not int or native["id"] <= 0
            or str(native.get("repository_url", "")).casefold() != "https://api.github.com/" + prefix):
        raise Refusal("Native Issue identity differs.")
    result = {"repository": {"name": reader.project.repository, "id": reader.project.repository_id, "database_id": repo["id"]},
              "issue": {"number": number, "node_id": issue["node_id"], "database_id": native["id"], "title": text(native.get("title")),
                        "body": text(native.get("body") or "", empty=True), "state": text(native.get("state"))},
              "issue_comments": _discussion(reader._get(f"{prefix}/issues/{number}/comments?per_page=100", paginated=True), "issue_comments"),
              "pr": None, "discussions": {}}
    if pr is None: return result
    number = pr["number"]
    value = reader._get(f"{prefix}/pulls/{number}")
    if (not isinstance(value, dict) or value.get("number") != number or value.get("node_id") != pr["node_id"]
            or type(value.get("id")) is not int or value["id"] <= 0 or type(value.get("draft")) is not bool):
        raise Refusal("Native Draft identity differs.")
    branches = {}
    for side in ("head", "base"):
        branch = value.get(side)
        if not isinstance(branch, dict) or not isinstance(branch.get("repo"), dict):
            raise Refusal("Native branch identity unavailable.")
        branches[side] = {"repository_id": text(branch["repo"].get("node_id")), "ref": text(branch.get("ref")), "sha": text(branch.get("sha"))}
        if not re.fullmatch(r"[0-9a-f]{40}", branches[side]["sha"]):
            raise Refusal("Native branch commit identity is invalid.")
    if branches["base"]["repository_id"] != reader.project.repository_id:
        raise Refusal("Native base repository differs.")
    body = value.get("body")
    if body is not None and not isinstance(body, str):
        raise Refusal("Native Draft body is invalid.")
    result["pr"] = {"number": number, "node_id": pr["node_id"], "database_id": value["id"], "title": text(value.get("title")),
                    "body": body, "state": text(value.get("state")),
                    "draft": value["draft"], **branches}
    endpoints = {"pull_request_issue_comments": f"{prefix}/issues/{number}/comments?per_page=100",
                 "pull_request_reviews": f"{prefix}/pulls/{number}/reviews?per_page=100",
                 "pull_request_review_comments": f"{prefix}/pulls/{number}/comments?per_page=100"}
    result["discussions"] = {name: _discussion(reader._get(endpoint, paginated=True), name) for name, endpoint in endpoints.items()}
    return result


def observe(reader: SourceReader, issue: dict, pr: dict | None) -> dict:
    first = _one(reader, issue, pr)
    second = _one(reader, issue, pr)
    if first != second:
        raise Refusal("Native observations changed between passes.")
    return {"status": "stable", "coverage": "two complete passes", "observation": second,
            "limits": ["Matching observations are not an atomic snapshot or continuing guarantee."]}


def action_context(native: dict) -> dict | None:
    """Select the exact comparable native facts; exclude fetch bookkeeping."""
    if native.get("status") != "stable" or native.get("coverage") != "two complete passes": return None
    obs = native["observation"]
    pr = obs.get("pr")
    if pr is None: return None
    from .draft_contracts import native_context
    return native_context({"repository": {"name": obs["repository"]["name"], "node_id": obs["repository"]["id"]},
                           "issue": {key: obs["issue"][key] for key in ("number", "node_id", "state", "title", "body")},
                           "pull_request": {**{key: pr[key] for key in ("number", "node_id", "state", "draft", "title", "body")},
                                            **{side: {"repository_id": pr[side]["repository_id"], "ref": pr[side]["ref"], "commit": pr[side]["sha"]} for side in ("head", "base")}},
                           "discussions": {"issue_comments": obs["issue_comments"], **obs["discussions"]}})

"""Independent read-only boundaries for evidence reports."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

from .contracts import Refusal, parse_json
from .draft_contracts import parse_draft, parse_draft_project, parse_issue, scan_markdown, subjects
from .draft_sources import observe
from .evidence_contracts import fields, identity, string
from .issue_check import SourceReader, read_text
from .issue_contracts import text_digest


def receipt(path: str) -> str:
    path = string(path)
    if not Path(path).is_absolute():
        raise Refusal("An absolute receipt location is required.")
    return read_text(Path(path))


def historical(upstream: dict, reader=receipt) -> dict:
    fields(upstream, {"project", "issue", "draft", "current_source_mode", "applicability"})
    if upstream["current_source_mode"] not in {"working", "installed"}:
        raise Refusal("Invalid source mode.")
    records = [parse_json(reader(upstream[key])) for key in ("project", "issue", "draft")]
    project, issue, draft = records
    parse_draft_project(project); parse_issue(issue); parse_draft(draft)
    ids = subjects(project, issue, draft)
    pa, ia, da = project["assessment"], issue["assessment"], draft["assessment"]
    details = {}
    for name, record, key, expected_scope in (
        ("project", pa, "subject_sha256", project["scope"]),
        ("issue", ia, "subject_sha256", issue["scope"]),
        ("draft_local", da, "local_subject_sha256", draft["trace"]["scope"]),
        ("draft_composition", da, "composition_subject_sha256", draft["trace"]["scope"]),
    ):
        subject_key = {"draft_local": "local", "draft_composition": "composition"}.get(name, name)
        details[name] = {"subject_matches": record is not None and record[key] == ids[subject_key],
                         "scope_matches": record is not None and record["scope"] == expected_scope}
    bindings = {name: detail["subject_matches"] and detail["scope_matches"] for name, detail in details.items()}
    return {"records": records, "subjects": ids, "bindings": bindings,
            "binding_details": details,
            "identity": identity("historical_upstream", {"subjects": ids, "assessments": [pa, ia, da]})}


def current(historical_result: dict, mode: str) -> dict:
    project, issue, draft = historical_result["records"]
    parsed = parse_draft_project(project)
    _, issue_sources = parse_issue(issue)
    reader = SourceReader(parsed, mode)
    reader.prepare()
    observations = {}
    for prefix, sources in (("project", parsed.sources), ("issue", issue_sources)):
        for source in sources:
            key = prefix + ":" + source.key
            if source.applicability == "not_applicable":
                observations[key] = {"status": "not_applicable"}
                continue
            try:
                observed = text_digest(reader.read(source))
                observations[key] = {"status": "matches" if observed == source.sha256 else "changed", "sha256": observed}
            except (Refusal, OSError, ValueError):
                observations[key] = {"status": "unavailable"}
    try:
        native = observe(reader, issue["issue"], draft["candidate"]["native_pr"])
    except (Refusal, OSError, ValueError):
        native = None
    return {"sources": observations, "native": native}


def select(text: str, selector: dict) -> str:
    if not isinstance(selector, dict):
        raise Refusal("Invalid selector.")
    kind = selector.get("kind")
    if kind == "whole":
        fields(selector, {"kind"}); return text
    if kind == "exact":
        fields(selector, {"kind", "start", "end"})
        start, end = selector["start"], selector["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(text):
            raise Refusal("Invalid range.")
        return text[start:end]
    if kind == "markdown_section":
        fields(selector, {"kind", "heading"}); heading = string(selector["heading"])
        scan = scan_markdown(text)
        if scan["findings"]:
            raise Refusal("Invalid Markdown.")
        found = [row for row in scan["headings"] if row["heading"] == heading]
        if len(found) != 1:
            raise Refusal("Ambiguous section.")
        return text[found[0]["content_start"]:found[0]["end"]]
    raise Refusal("Unsupported selector.")


def git_change(change: dict) -> dict:
    fields(change, {"root", "base_commit", "result_commit"})
    root = string(change["root"])
    if not Path(root).is_absolute():
        raise Refusal("Invalid repository path.")
    for key in ("base_commit", "result_commit"):
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", string(change[key])):
            raise Refusal("A full commit ID is required.")
    env = os.environ.copy()
    # `-C` alone does not override inherited repository, common-dir or object routing.
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                 "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_INDEX_FILE", "GIT_NAMESPACE",
                 "GIT_PREFIX", "GIT_SHALLOW_FILE", "GIT_GRAFT_FILE"):
        env.pop(name, None)
    env.update({"GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1", "LC_ALL": "C"})
    def run(*args: str) -> bytes:
        try:
            result = subprocess.run(["git", "-C", root, "--no-replace-objects", *args], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        except OSError:
            raise Refusal("Git unavailable.") from None
        if result.returncode:
            raise Refusal("Git observation unavailable.")
        return result.stdout
    commits, trees = [], []
    for key in ("base_commit", "result_commit"):
        obj = change[key]
        if run("cat-file", "-t", obj).strip() != b"commit":
            raise Refusal("Object is not a commit.")
        commits.append(obj)
        trees.append(run("rev-parse", "--verify", obj + "^{tree}").decode("ascii").strip())
    raw = run("diff-tree", "-r", "--raw", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", "--abbrev=64", *trees)
    parts = raw.split(b"\0")
    entries = []
    for index in range(0, len(parts) - 1, 2):
        header, path = parts[index:index + 2]
        if not header or not path:
            raise Refusal("Invalid Git output.")
        match = re.fullmatch(rb":([0-7]{6}) ([0-7]{6}) ([0-9a-f]+) ([0-9a-f]+) ([A-Z])", header)
        if not match:
            raise Refusal("Unsupported Git output.")
        old_mode, new_mode, old_id, new_id, status = (part.decode("ascii") for part in match.groups())
        entry = {"path_hex": path.hex(), "old_mode": old_mode, "new_mode": new_mode,
                 "old_object": old_id, "new_object": new_id, "status": status}
        entry["id"] = identity("git_entry", entry)
        entries.append(entry)
    repository = run("rev-parse", "--absolute-git-dir").decode("utf-8", "surrogateescape").strip()
    result = {"repository": repository, "commits": commits, "trees": trees, "entries": entries}
    result["identity"] = identity("git_change", result)
    return result

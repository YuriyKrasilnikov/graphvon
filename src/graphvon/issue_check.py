"""Read sources and check an Issue candidate; never publish or update records."""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Sequence
from urllib.parse import quote

from .contracts import Refusal, canonical_json, parse_json
from .issue_contracts import (
    ProjectBasis, Source, load_form, obj, parse_project, parse_proposal,
    project_subject, proposal_subject, render, text, text_digest,
)
from .sources import _discussion, _pages, _remote_repository


def read_text(path: Path) -> str:
    """Read an explicitly selected ordinary file; never wait on a FIFO."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise Refusal("A proposal-check source is not an ordinary file.")
            with os.fdopen(fd, encoding="utf-8", newline="", closefd=False) as stream:
                return stream.read()
        finally:
            os.close(fd)
    except (OSError, UnicodeError, ValueError):
        raise Refusal("A proposal-check source could not be read.") from None


def absolute_path(value: Any) -> Path:
    path = Path(text(value))
    if not path.is_absolute():
        raise Refusal("An explicit absolute private input location is required.")
    return path


class SourceReader:
    """Pin installed files to the observed default-branch head, using GET only.

    Other source reads are bounded observations, not an atomic snapshot or lock.
    """

    def __init__(self, project: ProjectBasis, mode: str):
        self.project = project
        self.mode = mode
        self.root = absolute_path(project.root).resolve(strict=True)
        self.revision: str | None = None

    def _run(self, arguments: list[str]) -> str:
        try:
            result = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", check=False)
            if result.returncode:
                raise Refusal("A source command failed; its outcome is unavailable.")
            return result.stdout
        except (OSError, UnicodeError):
            raise Refusal("A source command could not be completed.") from None

    def _get(self, endpoint: str, *, paginated: bool = False) -> Any:
        command = ["gh", "api", "--method", "GET", "--header", "Accept: application/vnd.github+json",
                   "--header", "X-GitHub-Api-Version: 2022-11-28", endpoint]
        if paginated:
            command.append("--paginate")
        return _pages(self._run(command), paginated)

    def prepare(self) -> None:
        actual_root = self._run(["git", "-C", str(self.root), "rev-parse", "--show-toplevel"]).strip()
        if Path(actual_root).resolve() != self.root:
            raise Refusal("The project basis is not bound to this checkout.")
        remote = self._run(["git", "-C", str(self.root), "remote", "get-url", "origin"]).strip()
        if _remote_repository(remote) != self.project.repository:
            raise Refusal("The project basis identifies a different repository.")
        repo = self._get("repos/" + self.project.repository)
        if repo.get("node_id") != self.project.repository_id or str(repo.get("full_name", "")).casefold() != self.project.repository:
            raise Refusal("The native repository identity could not be confirmed.")
        if self.mode == "installed":
            branch = text(repo.get("default_branch"))
            commit = self._get("repos/" + self.project.repository + "/commits/" + quote(branch, safe=""))
            self.revision = text(commit.get("sha"))
            if not re.fullmatch(r"[0-9a-f]{40}", self.revision):
                raise Refusal("The installed source revision could not be confirmed.")

    def read(self, source: Source) -> str:
        if source.kind == "local_file":
            return read_text(absolute_path(source.location))
        if source.kind == "repository_file":
            if self.mode == "working":
                path = (self.root / str(source.location)).resolve(strict=True)
                if not path.is_relative_to(self.root):
                    raise Refusal("Repository source resolves outside the checkout.")
                return read_text(path)
            if self.revision is None:
                raise Refusal("No installed source revision was observed.")
            endpoint = "repos/" + self.project.repository + "/contents/" + quote(str(source.location), safe="/") + "?ref=" + self.revision
            value = self._get(endpoint)
            if value.get("type") != "file" or value.get("encoding") != "base64":
                raise Refusal("The installed repository source is unavailable.")
            try:
                encoded = text(value.get("content"), empty=True)
                return base64.b64decode("".join(encoded.split()), validate=True).decode("utf-8")
            except (ValueError, UnicodeError):
                raise Refusal("The installed repository source is invalid.") from None
        prefix = "repos/" + self.project.repository
        value = self._get(f"{prefix}/issues/{source.location}")
        if "pull_request" in value or type(value.get("number")) is not int or value["number"] != source.location or str(value.get("repository_url", "")).casefold() != "https://api.github.com/" + prefix:
            raise Refusal("A requirement source is not the expected native Issue.")
        comments = self._get(f"{prefix}/issues/{source.location}/comments?per_page=100", paginated=True)
        body = value.get("body")
        return canonical_json({"id": text(value.get("node_id")), "title": text(value.get("title")),
                               "body": text("" if body is None else body, empty=True),
                               "comments": _discussion(comments, "issue_comments")})


def _heading_anchors(document: str) -> set[str]:
    """Resolve the initial profile's ATX headings outside fenced code blocks."""
    result = set()
    fence = None
    for line in document.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            found = marker.group(1)
            if fence is None:
                fence = found
            elif (found[0] == fence[0] and len(found) >= len(fence)
                  and not line[marker.end():].strip(" \t")):
                fence = None
            continue
        if fence is None:
            heading = re.match(r"^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
            if heading:
                result.add(re.sub(r"[^\w -]", "", heading.group(1).casefold()).replace(" ", "-"))
    return result


def _assessment_report(assessment: dict | None) -> dict:
    """Retain a supplied judgment's meaning without calling it machine proof."""
    if assessment is None:
        return {"applicability": "not_assessed", "performed_by_checker": False}
    names = ("preservation", "definition", "readiness", "publication")
    return {"applicability": "not_checked", "performed_by_checker": False,
            "declared_scope": assessment["scope"],
            "declared_results": {name: assessment[name]["result"] for name in names},
            "judgment_context": {
                "provenance": assessment["provenance"],
                "readiness_action": assessment["readiness"]["action"],
                "reasons": {name: list(assessment[name]["reasons"]) for name in names},
                "limits": list(assessment["limits"])}}


def check(project: ProjectBasis, proposal: dict, mode: str, reader: SourceReader | None = None) -> dict:
    if mode not in {"working", "installed"}:
        raise Refusal("Unsupported source observation mode.")
    result = {"mode": "working_candidate" if mode == "working" else "installed_profile",
              "structure": {"status": "unavailable", "findings": []},
              "source_coverage": {"status": "unknown", "findings": [], "sources": [],
                                  "project_assessment": {key: deepcopy(project.raw["assessment"][key])
                                                         for key in ("scope", "conclusion", "provenance", "limits")}},
              "declared_trace": deepcopy(proposal["trace"]),
              "semantic_assessment": _assessment_report(proposal["assessment"]),
              "public_payload": None,
              "limits": ["Source and assessment authority remain procedural.",
                         "Structural validity does not establish semantic preservation or permission to publish.",
                         "This operation performs no publication or record updates."]}
    coverage = result["source_coverage"]
    try:
        reader = reader or SourceReader(project, mode)
        reader.prepare()
    except (Refusal, OSError, ValueError):
        coverage["findings"].append("repository_unavailable_or_mismatched")
        return result
    candidate = proposal["candidate"]
    chosen = candidate["template"]
    source_by_key = {source.key: source for source in project.sources}
    trace_keys = set(proposal["trace"]["source_keys"])
    if trace_keys - source_by_key.keys():
        coverage["findings"].append("undeclared_trace_source")
    assessed = project.raw["assessment"]
    if assessed["subject_sha256"] != project_subject(project.raw) or assessed["scope"] != project.scope:
        coverage["findings"].append("project_assessment_stale")
    elif assessed["conclusion"] != "supported":
        coverage["findings"].append("project_assessment_unresolved")
    if proposal["trace"]["scope"] != project.scope:
        coverage["findings"].append("scope_mismatch")
    observations = {}
    contents = {}
    for source in project.sources:
        active = source.key in {project.entry_source, chosen} or source.applicability == "required"
        if source.applicability == "unknown":
            coverage["findings"].append("source_applicability_unknown")
        if not active:
            coverage["sources"].append({"source": source.key, "status": source.applicability})
            continue
        if source.applicability != "required":
            coverage["findings"].append("selected_source_not_applicable")
        if source.key not in trace_keys:
            coverage["findings"].append("required_source_omitted")
        try:
            contents[source.key] = reader.read(source)
            observed = text_digest(contents[source.key])
            observations[source.key] = observed
            status = "matches" if observed == source.sha256 else "changed"
        except (Refusal, OSError, ValueError):
            status = "unavailable"
        coverage["sources"].append({"source": source.key, "status": status})
        if status != "matches":
            coverage["findings"].append("source_" + status)
    entry = contents.get(project.entry_source)
    if entry is not None and project.entry_fragment not in _heading_anchors(entry):
        coverage["findings"].append("canonical_entry_fragment_missing")
    shape = result["structure"]
    if chosen not in project.templates:
        shape["findings"].append("template_not_permitted")
    elif chosen not in contents:
        shape["findings"].append("template_unavailable")
    else:
        try:
            form = load_form(contents[chosen])
            payload, findings = render(form, candidate["title"], candidate["fields"])
            shape["findings"].extend(findings)
            allowed_fields = {field.id for field in form.fields}
            for obligation in proposal["trace"]["obligations"]:
                refs = set(obligation["sources"]) | set(obligation.get("decision_sources", []))
                if refs - trace_keys or set(obligation["fields"]) - allowed_fields:
                    coverage["findings"].append("trace_reference_mismatch")
            result["public_payload"] = payload
        except Refusal:
            shape["findings"].append("unsupported_or_invalid_form")
    shape["status"] = "valid" if not shape["findings"] else "invalid"
    coverage["status"] = "consistent_with_assessed_basis" if not coverage["findings"] else "partial"
    if result["public_payload"] is not None:
        subject = proposal_subject(project, proposal, result["public_payload"], observations)
        result["subject_sha256"] = subject
        assessment = proposal["assessment"]
        if assessment is not None:
            applicable = (not coverage["findings"] and assessment["subject_sha256"] == subject
                          and assessment["scope"] == project.scope
                          and assessment["readiness"]["action"] == proposal["trace"]["next_action"])
            result["semantic_assessment"]["applicability"] = "matches_subject" if applicable else "stale_or_unresolved"
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check an Issue proposal without publishing or updating records.")
    parser.add_argument("operation", choices=["check"])
    parser.parse_args(argv)
    try:
        request = obj(parse_json(sys.stdin.read()), {"version", "project_basis", "proposal", "mode"})
        if type(request["version"]) is not int or request["version"] != 1:
            raise Refusal("Unsupported proposal-check request.")
        project = parse_project(parse_json(read_text(absolute_path(request["project_basis"]))))
        proposal = parse_proposal(parse_json(read_text(absolute_path(request["proposal"]))))
        print(json.dumps(check(project, proposal, request["mode"]), ensure_ascii=False, indent=2))
        return 0
    except (Refusal, OSError, ValueError, TypeError, RecursionError):
        print(json.dumps({"error": "The proposal check could not read a valid supported input; no mutation was performed."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

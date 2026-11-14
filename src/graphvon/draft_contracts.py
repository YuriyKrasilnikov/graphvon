"""Private Draft-checking contracts, references and content identities."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .contracts import Refusal, content_digest, parse_json, repository_name
from .issue_contracts import Source, digest, obj, parse_project, relative_path, strings, text
from .sources import _timestamp


def _version(value: Any) -> None:
    if type(value) is not int or value != 1:
        raise Refusal("Unsupported Draft record version.")


def _array(value: Any) -> list:
    if not isinstance(value, list):
        raise Refusal("Expected a list.")
    return value


def _unique(rows: list, key: str) -> None:
    ids = [text(row[key]) for row in rows]
    if len(ids) != len(set(ids)):
        raise Refusal("Duplicate record identifier.")


def action(value: Any) -> dict:
    value = obj(value, {"kind", "description"})
    if value["kind"] not in {"discuss", "publish", "implement"}:
        raise Refusal("Invalid named action.")
    text(value["description"])
    return value


def judgment(value: Any) -> None:
    value = obj(value, {"result", "reasons"})
    if value["result"] not in {"supported", "discrepancy", "unknown", "not_assessed"}:
        raise Refusal("Invalid substantive judgment.")
    strings(value["reasons"])


def plain_heading(value: Any) -> str:
    heading = text(value)
    if "\n" in heading or "\r" in heading or re.search(r"[`*_\[\]<>\\]", heading):
        raise Refusal("A plain single-line heading is required.")
    return heading


def source_ref(value: Any) -> dict:
    value = obj(value, {"source", "selector"})
    source = text(value["source"])
    if not (source.startswith("project:") or source.startswith("issue:")) or not source.split(":", 1)[1]:
        raise Refusal("A source reference requires a namespace.")
    selector = value["selector"]
    if not isinstance(selector, dict):
        raise Refusal("Invalid source selector.")
    kind = selector.get("kind")
    keys = {"kind", "target"}
    if kind == "exact":
        keys |= {"start", "end", "text"}
    elif kind == "markdown_section":
        keys.add("heading")
    elif kind != "whole":
        raise Refusal("Unsupported source selector.")
    obj(selector, keys)
    if selector["target"] not in {"source_text", "issue_body"}:
        raise Refusal("Unsupported selector target.")
    if kind == "exact":
        if type(selector["start"]) is not int or type(selector["end"]) is not int or selector["start"] < 0 or selector["end"] <= selector["start"]:
            raise Refusal("Invalid selection range.")
        text(selector["text"])
    if kind == "markdown_section":
        plain_heading(selector["heading"])
    return value


def refs(value: Any) -> None:
    for row in _array(value):
        source_ref(row)


def body_ref(value: Any) -> None:
    value = obj(value, {"heading", "start", "end", "text"})
    plain_heading(value["heading"])
    text(value["text"])
    if type(value["start"]) is not int or type(value["end"]) is not int or value["start"] < 0 or value["end"] <= value["start"]:
        raise Refusal("Invalid body selection range.")


def body_refs(value: Any) -> None:
    for item in _array(value):
        body_ref(item)


def native_context(value: Any) -> dict:
    """Validate and normalize an action snapshot without interpreting discussions."""
    value = obj(value, {"repository", "issue", "pull_request", "discussions"})
    repo = obj(value["repository"], {"name", "node_id"})
    name = repository_name(repo["name"]); text(repo["node_id"])
    issue = obj(value["issue"], {"number", "node_id", "state", "title", "body"})
    pr = obj(value["pull_request"], {"number", "node_id", "state", "draft", "title", "body", "head", "base"})
    for item in (issue, pr):
        native_identity({"number": item["number"], "node_id": item["node_id"]})
        if item["state"] not in {"open", "closed"}: raise Refusal("Invalid native lifecycle state.")
        text(item["title"])
        if item["body"] is not None: text(item["body"], empty=True)
    if type(pr["draft"]) is not bool: raise Refusal("Invalid Draft state.")
    for side in ("head", "base"):
        branch = obj(pr[side], {"repository_id", "ref", "commit"})
        text(branch["repository_id"]); text(branch["ref"])
        if not isinstance(branch["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", branch["commit"]):
            raise Refusal("Invalid native commit.")
    names = {"issue_comments", "pull_request_issue_comments", "pull_request_reviews", "pull_request_review_comments"}
    collections = obj(value["discussions"], names)
    normalized = {}
    for name_key in sorted(names):
        rows = _array(collections[name_key])
        for row in rows:
            obj(row, {"id", "updated_at", "submitted_at", "content_sha256"})
            text(row["id"]); digest(row["content_sha256"])
            _timestamp(row, "updated_at", nullable=True); _timestamp(row, "submitted_at", nullable=True)
        _unique(rows, "id")
        normalized[name_key] = sorted((dict(row) for row in rows), key=lambda row: row["id"])
    return {"repository": {"name": name, "node_id": repo["node_id"]}, "issue": dict(issue),
            "pull_request": dict(pr), "discussions": normalized}


def action_context_subject(action_value: dict, scope: str, identities: dict, basis: dict) -> str:
    return content_digest({"version": 1, "action": action_value, "assessment_scope": scope,
                           "local_subject_sha256": identities["local"], "composition_subject_sha256": identities["composition"],
                           "native": native_context(basis)})


def parse_draft_project(data: Any):
    obj(data, {"version", "root", "repository", "canonical_entry", "sources", "allowed_templates", "scope", "profiles", "assessment"})
    project = parse_project({key: value for key, value in data.items() if key != "profiles"})
    profiles = _array(data["profiles"])
    seen = set()
    for profile in profiles:
        obj(profile, {"template", "sections"})
        template = text(profile["template"])
        if template in seen or template not in project.templates:
            raise Refusal("Invalid Draft template profile.")
        seen.add(template)
        sections = _array(profile["sections"])
        for section in sections:
            obj(section, {"heading", "required", "rule_refs"})
            plain_heading(section["heading"])
            if type(section["required"]) is not bool or not _array(section["rule_refs"]):
                raise Refusal("Invalid Draft section profile.")
            refs(section["rule_refs"])
        _unique(sections, "heading")
        if not any(s["required"] for s in sections):
            raise Refusal("A Draft profile requires a section.")
    if seen != set(project.templates):
        raise Refusal("Each permitted template requires one profile.")
    return project


def _sources(rows: Any) -> list[Source]:
    rows = _array(rows)
    if not rows:
        raise Refusal("Sources are required.")
    result = []
    for row in rows:
        obj(row, {"key", "kind", "location", "sha256", "applicability", "basis", "owner", "status"})
        key, kind, location = text(row["key"]), row["kind"], row["location"]
        if kind == "github_issue":
            if type(location) is not int or location <= 0:
                raise Refusal("Invalid Issue source.")
        elif kind == "repository_file":
            relative_path(location)
        elif kind == "local_file":
            if not Path(text(location)).is_absolute():
                raise Refusal("Local source paths must be absolute.")
        else:
            raise Refusal("Unsupported source kind.")
        if row["applicability"] not in {"required", "not_applicable", "unknown"}:
            raise Refusal("Invalid source applicability.")
        for k in ("basis", "owner", "status"):
            text(row[k])
        result.append(Source(key, kind, location, digest(row["sha256"]), row["applicability"], row["basis"]))
    _unique(rows, "key")
    return result


def native_identity(value: Any, *, issue: bool = False) -> dict:
    value = obj(value, {"number", "node_id", "source"} if issue else {"number", "node_id"})
    if type(value["number"]) is not int or value["number"] <= 0:
        raise Refusal("Invalid native number.")
    text(value["node_id"])
    if issue:
        text(value["source"])
    return value


def parse_issue(data: Any) -> tuple[dict, list[Source]]:
    obj(data, {"schema_version", "artifact_id", "record_revision", "repository", "issue", "scope", "sources", "conditions", "obligations", "shared_constraints", "remaining", "unknowns", "assessment"})
    _version(data["schema_version"])
    for k in ("artifact_id", "record_revision", "scope"):
        text(data[k])
    repo = obj(data["repository"], {"name", "id"})
    repository_name(repo["name"])
    text(repo["id"])
    ident = native_identity(data["issue"], issue=True)
    sources = _sources(data["sources"])
    selected = [s for s in sources if s.key == ident["source"] and s.kind == "github_issue" and s.location == ident["number"] and s.applicability == "required"]
    if not selected:
        raise Refusal("The native Issue source is not declared.")
    conditions = _array(data["conditions"])
    obligations = _array(data["obligations"])
    constraints = _array(data["shared_constraints"])
    if not obligations:
        raise Refusal("A scoped Issue contract requires obligations.")
    for row in conditions:
        obj(row, {"id", "statement", "source_refs"}); text(row["statement"]); refs(row["source_refs"])
    for row in obligations:
        obj(row, {"id", "statement", "source_refs", "condition_ids", "acceptance"})
        text(row["statement"]); text(row["acceptance"]); refs(row["source_refs"]); strings(row["condition_ids"])
    for row in constraints:
        obj(row, {"id", "statement", "source_refs", "obligation_ids", "condition_ids"})
        text(row["statement"]); refs(row["source_refs"]); strings(row["obligation_ids"]); strings(row["condition_ids"])
    for rows in (conditions, obligations, constraints):
        _unique(rows, "id")
    strings(data["remaining"]); strings(data["unknowns"])
    assessment = data["assessment"]
    if assessment is not None:
        obj(assessment, {"subject_sha256", "provenance", "scope", "preservation", "publication", "actions", "limits", "supersedes"})
        digest(assessment["subject_sha256"]); text(assessment["provenance"]); text(assessment["scope"])
        judgment(assessment["preservation"]); judgment(assessment["publication"]); strings(assessment["limits"])
        seen = set()
        for item in _array(assessment["actions"]):
            obj(item, {"action", "definition", "adequacy"}); key = content_digest(action(item["action"]))
            if key in seen: raise Refusal("Duplicate action judgment.")
            seen.add(key); judgment(item["definition"]); judgment(item["adequacy"])
        if assessment["supersedes"] is not None:
            previous = obj(assessment["supersedes"], {"subject_sha256", "provenance", "reason"})
            digest(previous["subject_sha256"]); text(previous["provenance"]); text(previous["reason"])
    return data, sources


def parse_draft(data: Any) -> dict:
    obj(data, {"schema_version", "artifact_id", "record_revision", "candidate", "trace", "assessment"})
    _version(data["schema_version"]); text(data["artifact_id"]); text(data["record_revision"])
    candidate = obj(data["candidate"], {"template", "title", "body", "issue", "native_pr"})
    text(candidate["template"]); text(candidate["title"]); text(candidate["body"], empty=True)
    native_identity(candidate["issue"])
    if candidate["native_pr"] is not None: native_identity(candidate["native_pr"])
    trace = obj(data["trace"], {"scope", "action", "source_keys", "conditions", "unknowns", "remaining", "obligations", "effects", "constraints"})
    text(trace["scope"]); action(trace["action"])
    for key in ("source_keys", "conditions", "unknowns", "remaining"): strings(trace[key])
    for row in _array(trace["obligations"]):
        obj(row, {"issue_obligation", "coverage", "plan_refs", "verification", "remainder"})
        text(row["issue_obligation"]); text(row["verification"]); text(row["remainder"], empty=True); body_refs(row["plan_refs"])
        if row["coverage"] not in {"covered", "partial", "outside", "unknown"}: raise Refusal("Invalid coverage.")
    _unique(trace["obligations"], "issue_obligation")
    for row in _array(trace["effects"]):
        obj(row, {"id", "plan_refs", "kind", "issue_obligations", "source_refs", "rationale"})
        text(row["id"]); text(row["rationale"]); body_refs(row["plan_refs"]); strings(row["issue_obligations"]); refs(row["source_refs"])
        if row["kind"] not in {"implementation_step", "derived_obligation", "optional_proposal"}: raise Refusal("Invalid plan effect.")
    _unique(trace["effects"], "id")
    for row in _array(trace["constraints"]):
        obj(row, {"issue_constraint", "effect_ids", "plan_refs", "planning_witness", "planned_verification", "remaining_conditions"})
        text(row["issue_constraint"]); strings(row["effect_ids"]); body_refs(row["plan_refs"])
        text(row["planning_witness"]); text(row["planned_verification"]); strings(row["remaining_conditions"])
    _unique(trace["constraints"], "issue_constraint")
    assessed = data["assessment"]
    if assessed is not None:
        obj(assessed, {"local_subject_sha256", "composition_subject_sha256", "provenance", "scope", "local_preservation", "justification", "definition", "joint_constraints", "publication", "readiness", "limits"})
        digest(assessed["local_subject_sha256"]); digest(assessed["composition_subject_sha256"])
        text(assessed["provenance"]); text(assessed["scope"]); strings(assessed["limits"])
        for key in ("local_preservation", "justification", "definition", "joint_constraints", "publication"): judgment(assessed[key])
        readiness = obj(assessed["readiness"], {"action", "result", "reasons"}, {"native_context"}); action(readiness["action"])
        judgment({"result": readiness["result"], "reasons": readiness["reasons"]})
        receipt = readiness.get("native_context")
        if receipt is not None:
            obj(receipt, {"subject_sha256", "basis", "provenance", "scope", "applicability", "limits"})
            digest(receipt["subject_sha256"]); native_context(receipt["basis"])
            text(receipt["provenance"]); text(receipt["scope"]); judgment(receipt["applicability"]); strings(receipt["limits"])
    return data


def subjects(project: dict, issue: dict, draft: dict) -> dict:
    project_id = content_digest({k: v for k, v in project.items() if k != "assessment"})
    issue_id = content_digest({k: v for k, v in issue.items() if k not in {"assessment", "record_revision", "artifact_id"}})
    source = next(row for row in issue["sources"] if row["key"] == issue["issue"]["source"])
    projection = {k: issue[k] for k in ("issue", "scope", "conditions", "obligations", "shared_constraints", "remaining", "unknowns")}
    projection["native_source"] = source
    candidate = {k: v for k, v in draft["candidate"].items() if k != "native_pr"}
    local = content_digest({"project_subject": project_id, "candidate": candidate, "trace": draft["trace"], "issue_contract": projection})
    composition = content_digest({"local_subject": local, "issue_subject": issue_id, "issue_assessment": issue["assessment"]})
    return {"project": project_id, "issue": issue_id, "local": local, "composition": composition}


def _inline_closing(source: str, start: int, length: int) -> int | None:
    """Find the matching backtick run within the current paragraph."""
    position = start
    first = True
    marker = re.compile(r"(?<!`)" + re.escape("`" * length) + r"(?!`)")
    for line in source[start:].splitlines(keepends=True):
        if not first and (not line.strip() or re.match(r"^ {0,3}(?:#{1,6}[ \t]+|`{3,}|~{3,})", line)):
            return None
        match = marker.search(line)
        if match:
            return position + match.end()
        first = False
        position += len(line)
    return None


def scan_markdown(source: str) -> dict:
    """Scan the declared ATX/comment/fence subset without normalizing offsets."""
    headings = []
    findings = []
    content = list(source)
    comment = False
    fence = None
    inline_end = 0
    offset = 0
    for line in source.splitlines(keepends=True):
        if fence is not None:
            match = re.match(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)", line)
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1] and not match.group(2).strip():
                fence = None
                for j in range(len(line)): content[offset + j] = " "
            offset += len(line)
            continue
        in_inline = inline_end > offset
        opening_fence = None if comment or in_inline else re.match(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)", line)
        if opening_fence:
            marker = opening_fence.group(1)
            fence = (marker[0], len(marker))
            for j in range(len(line)): content[offset + j] = " "
            offset += len(line)
            continue
        visible = list(line)
        i = min(len(line), max(0, inline_end - offset))
        while i < len(line):
            if comment:
                end = line.find("-->", i)
                stop = len(line) if end < 0 else end + 3
                for j in range(i, stop): visible[j] = " "
                i = stop
                if end >= 0: comment = False
            elif line.startswith("<!--", i):
                comment = True
            elif line[i] == "`":
                end = i
                while end < len(line) and line[end] == "`": end += 1
                backslashes = 0
                while i - backslashes - 1 >= 0 and line[i - backslashes - 1] == "\\": backslashes += 1
                closing = None if backslashes % 2 else _inline_closing(source, offset + end, end - i)
                if closing is not None:
                    inline_end = closing
                    i = min(len(line), inline_end - offset)
                else:
                    i = end
            else:
                i += 1
        plain = "".join(visible)
        for j, char in enumerate(visible):
            if char == " " and line[j] != " ": content[offset + j] = " "
        fence_match = None if in_inline else re.match(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)", plain)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1] and not fence_match.group(2).strip():
                fence = None
            for j in range(len(line)): content[offset + j] = " "
            offset += len(line)
            continue
        if fence is None and not in_inline:
            match = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*(?:\r?\n)?$", plain)
            if match:
                name = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2)).strip()
                if not name or re.search(r"[`*_\[\]<>\\]", name):
                    findings.append("markdown_profile_unsupported")
                else:
                    headings.append({"heading": name, "level": len(match.group(1)), "start": offset, "content_start": offset + len(line)})
                for j in range(len(line)): content[offset + j] = " "
            elif re.match(r"^ {0,3}(?:=+|-+)[ \t]*(?:\r?\n)?$", plain) or re.match(r"^\s*(?:<h[1-6]\b|(?:>|[-+*]|\d+[.)])[ \t]+#{1,6}\s| {4,}#{1,6}\s|#{1,6}[^#\s])", plain, re.I):
                findings.append("markdown_profile_unsupported")
        offset += len(line)
    if comment or fence is not None: findings.append("markdown_profile_unsupported")
    for index, heading in enumerate(headings):
        heading["end"] = next((h["start"] for h in headings[index + 1:] if h["level"] <= heading["level"]), len(source))
    return {"headings": headings, "findings": findings, "content": "".join(content)}


def resolve_source_ref(ref: dict, source: Source | None, observed: str | None, expected_node: str | None = None) -> tuple[str | None, str | None]:
    """Return a selected string or a bounded diagnostic; never repair references."""
    if source is None: return None, "source_undeclared"
    if observed is None: return None, "source_unavailable"
    selector = ref["selector"]
    value = observed
    if selector["target"] == "issue_body":
        if source.kind != "github_issue": return None, "selector_target_unsupported"
        try:
            native = parse_json(observed)
            if not isinstance(native, dict) or not isinstance(native.get("body"), str) or (expected_node is not None and native.get("id") != expected_node):
                return None, "selector_target_invalid"
            value = native["body"]
        except (Refusal, ValueError):
            return None, "selector_target_invalid"
    if selector["kind"] == "whole": return value, None
    if selector["kind"] == "exact":
        start, end = selector["start"], selector["end"]
        if end > len(value): return None, "selection_out_of_bounds"
        if value[start:end] != selector["text"]: return None, "selection_text_mismatch"
        return value[start:end], None
    if selector["target"] == "source_text" and (source.kind == "github_issue" or str(source.location).casefold().endswith((".html", ".htm"))):
        return None, "selector_target_unsupported"
    scan = scan_markdown(value)
    if scan["findings"]: return None, "markdown_profile_unsupported"
    found = [h for h in scan["headings"] if h["heading"] == selector["heading"]]
    if not found: return None, "heading_missing"
    if len(found) != 1: return None, "heading_ambiguous"
    return value[found[0]["start"]:found[0]["end"]], None

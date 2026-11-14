"""Produce a read-only Draft assessment report; never grant admission."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import sys
from typing import Sequence

from .contracts import Refusal, parse_json
from .draft_contracts import action_context_subject, native_context, parse_draft, parse_draft_project, parse_issue, resolve_source_ref, scan_markdown, subjects
from .draft_sources import action_context, observe
from .issue_check import SourceReader, _heading_anchors, absolute_path, read_text
from .issue_contracts import obj, text_digest


def _declared(assessment, binding: str, expected: str, scope: str, availability: str) -> dict:
    if assessment is None:
        return {"applicability": "not_assessed", "performed_by_checker": False}
    state = (availability if availability != "current" else
             "applicable" if assessment[binding] == expected and assessment["scope"] == scope else "stale")
    return {"applicability": state, "performed_by_checker": False, "declared": deepcopy(assessment)}


def _aggregate(judgments: list[tuple[str, str]], prerequisites: bool) -> str:
    if any(app == "applicable" and result == "discrepancy" for app, result in judgments):
        return "discrepancy_reported"
    if not judgments or (any(app == "not_assessed" for app, _ in judgments)
                         and all(app == "not_assessed" or (app == "applicable" and result == "supported")
                                 for app, result in judgments)):
        return "not_assessed"
    if prerequisites and all(app == "applicable" and result == "supported" for app, result in judgments):
        return "supported_by_applicable_assessment"
    return "unknown"


def _judgment(report: dict, key: str) -> tuple[str, str]:
    return (report["applicability"], report.get("declared", {}).get(key, {}).get("result", "not_assessed"))


def _differences(previous, current, prefix="") -> list[str]:
    if isinstance(previous, dict) and isinstance(current, dict):
        result = []
        for key in sorted(previous.keys() | current.keys()):
            name = f"{prefix}.{key}" if prefix else key
            if key not in previous or key not in current: result.append(name)
            else: result.extend(_differences(previous[key], current[key], name))
        return result
    return [] if previous == current else [prefix]


def check(project_data: dict, issue: dict, draft: dict, mode: str, reader: SourceReader | None = None, native_observer=observe) -> dict:
    if mode not in {"working", "installed"}: raise Refusal("Unsupported source mode.")
    project = parse_draft_project(project_data)
    issue, issue_sources = parse_issue(issue)
    draft = parse_draft(draft)
    if issue["repository"]["name"].casefold() != project.repository or issue["repository"]["id"] != project.repository_id:
        raise Refusal("Issue and project repositories differ.")
    ids = subjects(project_data, issue, draft)
    result = {"version": 1, "mode": "working_candidate" if mode == "working" else "installed_profile",
              "structure": {"status": "unknown", "findings": []}, "references": {"status": "unknown", "findings": []},
              "source_coverage": {"status": "unknown", "sources": [], "findings": []}, "subjects": ids,
              "assessments": {}, "local_correspondence": {}, "composition": {}, "definition": {}, "next_action": {},
              "native": {"status": "unavailable", "pr": "not_requested" if draft["candidate"]["native_pr"] is None else "unavailable"},
              "public_payload": {"title": draft["candidate"]["title"], "body": draft["candidate"]["body"]},
              "limits": ["Semantic authority and source completeness remain procedural.", "Native reads are bounded observations, not an atomic snapshot.",
                         "No report grants write permission or implementation admission."]}
    coverage = result["source_coverage"]
    observed = {}
    all_sources = {"project:" + s.key: s for s in project.sources}
    all_sources.update({"issue:" + s.key: s for s in issue_sources})
    try:
        reader = reader or SourceReader(project, mode)
        reader.prepare()
    except (Refusal, OSError, ValueError):
        reader = None
        coverage["findings"].append("repository_unavailable_or_mismatched")
    for key, source in all_sources.items():
        if source.applicability == "not_applicable":
            coverage["sources"].append({"source": key, "status": "not_applicable"}); continue
        if source.applicability == "unknown": coverage["findings"].append("source_applicability_unknown")
        try:
            if reader is None: raise Refusal("Source reader unavailable.")
            value = reader.read(source)
            observed[key] = value
            status = "matches" if text_digest(value) == source.sha256 else "changed"
        except (Refusal, OSError, ValueError): status = "unavailable"
        coverage["sources"].append({"source": key, "status": status})
        if status != "matches": coverage["findings"].append("source_" + status)
    coverage["status"] = "consistent" if not coverage["findings"] else "partial"
    source_status = {entry["source"]: entry["status"] for entry in coverage["sources"]}
    project_ok = all(source_status["project:" + s.key] == "matches" for s in project.sources if s.applicability == "required") and all(s.applicability != "unknown" for s in project.sources)
    issue_ok = all(source_status["issue:" + s.key] == "matches" for s in issue_sources if s.applicability == "required") and all(s.applicability != "unknown" for s in issue_sources)
    entry = observed.get("project:" + project.entry_source)
    if entry is None or project.entry_fragment not in _heading_anchors(entry):
        project_ok = False; coverage["findings"].append("canonical_entry_fragment_unavailable")
    candidate = draft["candidate"]
    profile = next((p for p in project_data["profiles"] if p["template"] == candidate["template"]), None)
    shape = result["structure"]["findings"]
    template = observed.get("project:" + candidate["template"])
    if profile is None: shape.append("template_not_permitted")
    if template is None: shape.append("template_unavailable")
    scan = scan_markdown(candidate["body"])
    shape.extend(scan["findings"])
    headings = scan["headings"]
    level_two = [h["heading"] for h in headings if h["level"] == 2]
    if len(level_two) != len(set(level_two)): shape.append("duplicate_heading")
    if profile is not None and template is not None:
        templ = scan_markdown(template)
        shape.extend(templ["findings"])
        template_headings = [h["heading"] for h in templ["headings"] if h["level"] == 2]
        if len(template_headings) != len(set(template_headings)) or set(template_headings) != {x["heading"] for x in profile["sections"]}:
            shape.append("template_profile_mismatch")
        for section in profile["sections"]:
            matches = [h for h in headings if h["level"] == 2 and h["heading"] == section["heading"]]
            if len(matches) > 1: shape.append("duplicate_required_heading")
            elif section["required"] and not matches: shape.append("required_heading_missing")
            elif section["required"] and not scan["content"][matches[0]["content_start"]:matches[0]["end"]].strip(): shape.append("required_section_empty")
    result["structure"]["status"] = "valid" if not shape else "invalid"
    findings = result["references"]["findings"]
    declarations = []
    for profile in project_data["profiles"]:
        for section in profile["sections"]:
            for ref in section["rule_refs"]:
                if not ref["source"].startswith("project:"):
                    findings.append({"source": ref["source"], "finding": "project_rule_source_invalid"})
                declarations.append((ref, "local"))
    for row in issue["conditions"] + issue["obligations"] + issue["shared_constraints"]:
        declarations.extend((ref, "upstream") for ref in row["source_refs"])
    for row in draft["trace"]["effects"]:
        declarations.extend((ref, "local") for ref in row["source_refs"])
    for ref, consumer in declarations:
        key = ref["source"]
        source = all_sources.get(key)
        node = issue["issue"]["node_id"] if key == "issue:" + issue["issue"]["source"] else None
        _, finding = resolve_source_ref(ref, source, observed.get(key), node)
        if finding: findings.append({"source": key, "finding": finding, "consumer": consumer})
        elif source.applicability != "required": findings.append({"source": key, "finding": "source_not_applicable", "consumer": consumer})
        elif source_status.get(key) != "matches": findings.append({"source": key, "finding": "source_changed", "consumer": consumer})
    obligation_ids = {x["id"] for x in issue["obligations"]}; condition_ids = {x["id"] for x in issue["conditions"]}
    constraint_ids = {x["id"] for x in issue["shared_constraints"]}; effect_ids = {x["id"] for x in draft["trace"]["effects"]}
    if {x["issue_obligation"] for x in draft["trace"]["obligations"]} != obligation_ids: findings.append({"finding": "obligation_enumeration_mismatch"})
    if {x["issue_constraint"] for x in draft["trace"]["constraints"]} != constraint_ids: findings.append({"finding": "constraint_enumeration_mismatch"})
    for row in issue["obligations"] + issue["shared_constraints"]:
        if set(row["condition_ids"]) - condition_ids or set(row.get("obligation_ids", [])) - obligation_ids: findings.append({"finding": "issue_reference_mismatch"})
    for row in draft["trace"]["effects"]:
        if set(row["issue_obligations"]) - obligation_ids: findings.append({"finding": "effect_reference_mismatch"})
    for row in draft["trace"]["constraints"]:
        if set(row["effect_ids"]) - effect_ids: findings.append({"finding": "constraint_reference_mismatch"})
    if set(draft["trace"]["source_keys"]) - {s.key for s in project.sources}: findings.append({"finding": "source_undeclared"})
    for row in draft["trace"]["obligations"] + draft["trace"]["effects"] + draft["trace"]["constraints"]:
        for ref in row["plan_refs"]:
            matches = [h for h in headings if h["level"] == 2 and h["heading"] == ref["heading"]]
            start, end = ref["start"], ref["end"]
            selected = candidate["body"][start:end]
            clean = scan["content"][start:end]
            if (len(matches) != 1 or end > len(candidate["body"]) or selected != ref["text"]
                    or start < matches[0]["content_start"] or end > matches[0]["end"] or not clean.strip()
                    or any(not original.isspace() and masked == " " for original, masked in zip(selected, clean))):
                findings.append({"finding": "body_reference_invalid"})
    result["references"]["status"] = "valid" if not findings else "invalid"
    project_assessment = project_data["assessment"]
    project_applicable = project_ok and project_assessment["subject_sha256"] == ids["project"] and project_assessment["scope"] == project.scope and project_assessment["conclusion"] == "supported"
    assessment = issue["assessment"]
    def availability(prefix, sources):
        statuses = [source_status[prefix + source.key] for source in sources if source.applicability == "required"]
        if "unavailable" in statuses or any(source.applicability == "unknown" for source in sources): return "unavailable"
        if "changed" in statuses: return "stale"
        return "current"
    project_availability = availability("project:", project.sources)
    if project_availability == "current" and not project_ok:
        project_availability = "stale"
    issue_availability = availability("issue:", issue_sources)
    ia = _declared(assessment, "subject_sha256", ids["issue"], issue["scope"], issue_availability)
    da = draft["assessment"]
    primary_status = source_status.get("issue:" + issue["issue"]["source"])
    local_availability = ("unavailable" if project_availability == "unavailable" or primary_status == "unavailable" else
                          "stale" if project_availability == "stale" or primary_status != "matches" else "current")
    local = _declared(da, "local_subject_sha256", ids["local"], draft["trace"]["scope"], local_availability)
    combined_availability = ("unavailable" if "unavailable" in {project_availability, issue_availability} else
                             "stale" if "stale" in {project_availability, issue_availability} else "current")
    composition = _declared(da, "composition_subject_sha256", ids["composition"], draft["trace"]["scope"], combined_availability)
    project_state = (project_availability if project_availability != "current" else
                     "applicable" if project_assessment["subject_sha256"] == ids["project"] and project_assessment["scope"] == project.scope else "stale")
    result["assessments"] = {"project": {"applicability": project_state, "performed_by_checker": False, "declared": deepcopy(project_assessment)},
                              "issue": ia, "draft_local": local, "draft_composition": composition}
    native_issue = {"number": issue["issue"]["number"], "node_id": issue["issue"]["node_id"]}
    if candidate["issue"] != native_issue: findings.append({"finding": "issue_identity_mismatch"})
    if reader is not None:
        try: result["native"] = native_observer(reader, native_issue, candidate["native_pr"])
        except (Refusal, OSError, ValueError): result["native"] = {"status": "unavailable", "pr": "not_requested" if candidate["native_pr"] is None else "unavailable"}
    native = result["native"]
    correspondence = False
    if native.get("status") == "stable":
        obs = native["observation"]
        raw_issue = observed.get("issue:" + issue["issue"]["source"])
        try: native_issue_content = parse_json(raw_issue) if raw_issue is not None else None
        except Refusal: native_issue_content = None
        correspondence = bool(native_issue_content and obs["issue"]["title"] == native_issue_content["title"]
                              and obs["issue"]["body"] == native_issue_content["body"]
                              and obs["issue_comments"] == native_issue_content["comments"]
                              and candidate["issue"] == native_issue
                              and source_status.get("issue:" + issue["issue"]["source"]) == "matches")
        if candidate["native_pr"] is not None:
            native["candidate_matches"] = bool(obs["pr"] and obs["pr"]["title"] == candidate["title"] and obs["pr"]["body"] == candidate["body"])
        else: native["pr_status"] = "not_requested"
    result["references"]["status"] = "valid" if not findings else "invalid"
    project_judgment = (project_state, project_assessment["conclusion"])
    local_judgments = [project_judgment, _judgment(local, "local_preservation"), _judgment(local, "justification")]
    local_findings = [f for f in findings if f.get("consumer") != "upstream"
                      or f.get("source") == "issue:" + issue["issue"]["source"]]
    valid_local = project_applicable and not shape and not local_findings and correspondence
    local_status = _aggregate(local_judgments, valid_local)
    result["local_correspondence"] = {"status": local_status, "native_issue_matches": correspondence}
    joint = _judgment(composition, "joint_constraints")
    issue_preservation = _judgment(ia, "preservation")
    composition_status = _aggregate(local_judgments + [joint, issue_preservation], valid_local and issue_ok and not findings and local_status == "supported_by_applicable_assessment")
    result["composition"] = {"status": composition_status, "joint_constraints": joint[1], "issue_sources_current": issue_ok}
    action = draft["trace"]["action"]
    upstream_action = next((x for x in (assessment or {}).get("actions", []) if x["action"] == action), None)
    up_definition = (ia["applicability"], upstream_action["definition"]["result"] if upstream_action else "not_assessed")
    up_adequacy = (ia["applicability"], upstream_action["adequacy"]["result"] if upstream_action else "not_assessed")
    draft_definition = _judgment(local, "definition")
    result["definition"] = {"issue": up_definition[1], "draft": draft_definition[1], "issue_applicability": up_definition[0], "draft_applicability": draft_definition[0]}
    ready = (local["applicability"], (da or {}).get("readiness", {}).get("result", "not_assessed"))
    if da and da["readiness"]["action"] != action: ready = ("stale", ready[1])
    receipt = (da or {}).get("readiness", {}).get("native_context")
    requirement = "required" if action["kind"] == "implement" else "declared" if receipt is not None else "candidate_only"
    try:
        current_basis = action_context(native)
    except (Refusal, KeyError, TypeError, ValueError):
        current_basis = None
    assessed_basis = native_context(receipt["basis"]) if receipt else None
    context_state = "not_assessed"
    differences = []
    assessed_subject = receipt["subject_sha256"] if receipt else None
    current_subject = action_context_subject(action, da["scope"], ids, current_basis) if da and current_basis else None
    if receipt is not None:
        internal = action_context_subject(action, da["scope"], ids, assessed_basis)
        semantic_binding = (da["scope"] == draft["trace"]["scope"] and da["readiness"]["action"] == action
                            and da["local_subject_sha256"] == ids["local"] and da["composition_subject_sha256"] == ids["composition"])
        if receipt["scope"] != da["scope"] or internal != assessed_subject or not semantic_binding:
            context_state = "stale"
            differences.append("receipt_binding")
        elif current_basis is None:
            context_state = "unavailable"
        elif current_subject != assessed_subject:
            context_state = "stale"
            differences = _differences(assessed_basis, current_basis)
        else:
            context_state = "applicable"
    result["action_context"] = {"requirement": requirement, "applicability": context_state,
                                "assessed_subject_sha256": assessed_subject, "current_subject_sha256": current_subject,
                                "assessed_basis": assessed_basis, "current_basis": current_basis,
                                "declared_judgment": deepcopy(receipt["applicability"]) if receipt else None,
                                "provenance": receipt["provenance"] if receipt else None,
                                "scope": receipt["scope"] if receipt else None,
                                "limits": list(receipt["limits"]) if receipt else [], "differences": differences,
                                "performed_by_checker": False}
    required = [ready, up_adequacy, joint, issue_preservation] + local_judgments
    if action["kind"] == "implement": required += [up_definition, draft_definition]
    if action["kind"] == "publish": required += [_judgment(local, "publication")]
    if requirement != "candidate_only":
        required.append((context_state, receipt["applicability"]["result"] if receipt else "not_assessed"))
    native_ok = True
    if action["kind"] == "implement":
        pr = native.get("observation", {}).get("pr") or {}
        native_ok = (native.get("status") == "stable" and native.get("candidate_matches") is True
                     and candidate["native_pr"] is not None and pr.get("state") == "open" and pr.get("draft") is True)
    status = _aggregate(required, composition_status == "supported_by_applicable_assessment" and native_ok)
    if requirement == "required" and receipt is None and status != "discrepancy_reported": status = "unknown"
    result["next_action"] = {"action": action, "status": status, "native_predicates_met": native_ok,
                             "basis": "candidate_only" if requirement == "candidate_only" else "native_context_bound"}
    coverage["status"] = "consistent" if not coverage["findings"] else "partial"
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Draft plan checks.")
    parser.add_argument("operation", choices=["check"])
    parser.parse_args(argv)
    try:
        request = obj(parse_json(sys.stdin.read()), {"version", "project_basis", "issue_contract", "draft", "mode"})
        if type(request["version"]) is not int or request["version"] != 1: raise Refusal("Unsupported request.")
        records = [parse_json(read_text(absolute_path(request[key]))) for key in ("project_basis", "issue_contract", "draft")]
        print(json.dumps(check(*records, request["mode"]), ensure_ascii=False, indent=2))
        return 0
    except (Refusal, OSError, ValueError, TypeError, KeyError, RecursionError):
        print(json.dumps({"error": "The Draft check could not read valid supported input; no mutation was performed."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

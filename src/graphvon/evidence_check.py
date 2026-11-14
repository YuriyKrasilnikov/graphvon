"""Report consistency and supplied applicability, without deciding acceptance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .contracts import Refusal, parse_json
from .evidence_contracts import assessment, fields, identity, root, string, strings
from .evidence_sources import current, git_change, historical, receipt, select


def _selection(row, reader):
    fields(row, {"id", "original", "retained_text", "current", "continuity"})
    sid = string(row["id"]); retained = string(row["retained_text"], empty=True)
    for name in ("original", "current"):
        ref = fields(row[name], {"locator", "selector", "provenance"})
        string(ref["locator"]); string(ref["provenance"])
        if not Path(ref["locator"]).is_absolute() or not isinstance(ref["selector"], dict):
            raise Refusal("Invalid selection reference.")
        # Validate the original selector even when its historical file is absent.
        if ref["selector"].get("kind") == "whole":
            fields(ref["selector"], {"kind"})
        elif ref["selector"].get("kind") == "exact":
            fields(ref["selector"], {"kind", "start", "end"})
            a, b = ref["selector"]["start"], ref["selector"]["end"]
            if type(a) is not int or type(b) is not int or not 0 <= a <= b:
                raise Refusal("Invalid range.")
        elif ref["selector"].get("kind") == "markdown_section":
            fields(ref["selector"], {"kind", "heading"}); string(ref["selector"]["heading"])
        else:
            raise Refusal("Invalid selector.")
    original = identity("original_selection", {"id": sid, "reference": row["original"], "text": retained})
    declared = {"original": row["original"], "current": row["current"], "retained_text": retained}
    target_id = identity("current_selection", {"reference": row["current"], "text": retained})
    continuity_subject = identity("continuity", {"original": original, "current": target_id})
    same_reference = row["original"] == row["current"]
    try:
        text = reader(row["current"]["locator"])
    except (Refusal, OSError, ValueError, UnicodeError):
        return {"id": sid, "status": "unavailable", "original_identity": original, "current_identity": None,
                "target_identity": target_id, "reference_changed": not same_reference,
                "declared": declared, "continuity": assessment(row["continuity"], continuity_subject), "usable": False}
    try:
        selected = select(text, row["current"]["selector"])
    except (Refusal, ValueError, TypeError):
        return {"id": sid, "status": "selection_invalid", "original_identity": original, "current_identity": None,
                "target_identity": target_id, "reference_changed": not same_reference,
                "declared": declared, "continuity": assessment(row["continuity"], continuity_subject), "usable": False}
    current_id = identity("current_selection", {"reference": row["current"], "text": selected})
    continuity = assessment(row["continuity"], continuity_subject)
    status = "changed" if selected != retained else "matches"
    usable = status == "matches" and (same_reference or (continuity["status"] == "applicable" and row["continuity"]["result"] == "supported"))
    return {"id": sid, "status": status, "original_identity": original, "current_identity": current_id, "target_identity": target_id,
            "declared": declared, "current_text": selected,
            "reference_changed": not same_reference, "continuity": continuity, "usable": usable}


def check(value, current_reader=current, receipt_reader=receipt, git_reader=git_change):
    root(value)
    result = {"supplied": {"status": "unvalidated", "upstream": value["upstream"], "change": value["change"],
                           "selections": value["selections"], "observations": value["observations"],
                           "correspondence": value["correspondence"], "claim": value["claim"],
                           "joint_assessment": value["joint_assessment"], "decision": value["decision"]},
              "historical_upstream": {"status": "unavailable"},
              "current_applicability": {"status": "unavailable", "assessment": assessment(value["upstream"].get("applicability"), None)},
              "selections": [], "git_changes": {"status": "unavailable"}, "evidence": [],
              "correspondence": {"status": "unavailable", "declared": value["correspondence"]},
              "claim": {"status": "unavailable", "current_usability": "unavailable", "declared": value["claim"],
                        "joint_assessment": {"status": "unavailable", "declared": value["joint_assessment"]}},
              "decision": ({"status": "not_assessed"} if value["decision"] is None else
                           {"status": "unavailable", "current_usability": "unavailable", "declared": value["decision"]}),
              "findings": [],
              "graph_edges": [],
              "limits": ["Supplied assessments are not performed by this checker.",
                         "Declared provenance is not authenticated; concealed authority changes may be undetectable.",
                         "A report or exit status does not grant acceptance or permission."]}
    hist = None; change = None
    try:
        hist = historical(value["upstream"], receipt_reader)
        result["historical_upstream"] = {"status": "available", "subjects": hist["subjects"],
                                         "bindings": hist["bindings"], "identity": hist["identity"],
                                         "binding_details": hist.get("binding_details", {}),
                                         "assessments": [record["assessment"] for record in hist["records"]],
                                         "declarations": {"obligations": hist["records"][1]["obligations"],
                                                          "constraints": hist["records"][1]["shared_constraints"],
                                                          "conditions": hist["records"][1]["conditions"],
                                                          "effects": hist["records"][2]["trace"]["effects"]}}
    except (Refusal, OSError, ValueError, TypeError, KeyError):
        result["findings"].append({"code": "historical_unavailable"})
    if hist is not None:
        try:
            observed = current_reader(hist, value["upstream"]["current_source_mode"])
            current_id = identity("current_sources", observed)
            complete = observed.get("native") is not None and all(
                entry.get("status") != "unavailable" for entry in observed.get("sources", {}).values())
            subject = identity("upstream_applicability", {"historical": hist["identity"], "current": current_id, "scope": value["scope"]}) if complete else None
            result["current_applicability"] = {"status": "available" if complete else "partial", "identity": current_id,
                                                "sources": observed.get("sources", {}),
                                                "native": "available" if observed.get("native") is not None else "unavailable",
                                                "assessment": assessment(value["upstream"]["applicability"], subject)}
        except (Refusal, OSError, ValueError, TypeError, KeyError):
            result["findings"].append({"code": "current_sources_unavailable"})
    try:
        change = git_reader(value["change"])
        result["git_changes"] = {"status": "available", **change}
    except (Refusal, OSError, ValueError, TypeError, KeyError):
        result["findings"].append({"code": "git_unavailable"})
    selections = {}; selection_records = {}; cache = {}
    def once(path):
        if path not in cache:
            try: cache[path] = (True, receipt_reader(path))
            except (Refusal, OSError, ValueError, UnicodeError): cache[path] = (False, None)
        if not cache[path][0]: raise Refusal("Receipt unavailable.")
        return cache[path][1]
    for row in value["selections"]:
        try:
            item = _selection(row, once); sid = item["id"]
            if sid in selections: raise Refusal("Duplicate selection.")
            selections[sid] = item; selection_records[sid] = row; result["selections"].append(item)
        except (Refusal, TypeError, KeyError, ValueError):
            result["findings"].append({"code": "invalid_selection"})
    observations = {}; observation_records = {}
    for row in value["observations"]:
        try:
            base_keys = {"id", "selection_id", "kind", "original_subject", "result", "conditions", "limits"}
            if not isinstance(row, dict) or base_keys - row.keys() or row.keys() - base_keys - {"applications"}:
                raise Refusal("Invalid observation fields.")
            oid = string(row["id"]); sid = string(row["selection_id"])
            if oid in observations or sid not in selections or row["kind"] not in {"planned", "reported_execution", "native_observation", "assessment"}:
                raise Refusal("Invalid observation.")
            subj = row["original_subject"]
            if not isinstance(subj, dict) or subj.get("kind") not in {"commit", "retained"}:
                raise Refusal("Invalid original subject.")
            if subj["kind"] == "commit":
                import re
                fields(subj, {"kind", "commit"})
                if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", string(subj["commit"])): raise Refusal("Invalid commit.")
            else: fields(subj, {"kind", "description"}); string(subj["description"])
            string(row["result"]); strings(row["conditions"]); strings(row["limits"])
            selected = selections[sid]
            original = identity("observation", {"selection": selected["original_identity"], **{k: row[k] for k in ("kind", "original_subject", "result", "conditions", "limits")}})
            selection_record = selection_records[sid]
            use = identity("current_use", {"observation": original, "current": selected["target_identity"], "continuity": selection_record["continuity"] if selected.get("reference_changed") else None})
            apps = []
            container_valid = isinstance(row.get("applications"), list)
            if not container_valid:
                result["findings"].append({"code": "invalid_applications", "id": oid})
            for index, app in enumerate(row["applications"] if container_valid else []):
                try:
                    fields(app, {"scope", "current_conditions", "assessment"}); scope = fields(app["scope"], {"obligation_ids", "constraint_ids", "property"})
                    strings(scope["obligation_ids"]); strings(scope["constraint_ids"]); string(scope["property"]); strings(app["current_conditions"])
                    target = None if change is None else identity("application", {"current_use": use, "change": change["identity"], "scope": scope, "conditions": app["current_conditions"]})
                    apps.append({"status": "valid", "scope": scope, "current_conditions": app["current_conditions"],
                                 "assessment": assessment(app["assessment"], target), "usable": selected["usable"]})
                except (Refusal, TypeError, KeyError, ValueError):
                    apps.append({"status": "invalid", "declared": app})
                    result["findings"].append({"code": "invalid_application", "id": oid, "index": index})
            item = {"id": oid, "kind": row["kind"], "original_identity": original, "current_use": use, "applications": apps,
                    "selection_status": selected["status"], "selection_usable": selected["usable"], "applications_valid": container_valid,
                    "declared": {key: row[key] for key in ("selection_id", "original_subject", "result", "conditions", "limits")}}
            observations[oid] = item; observation_records[oid] = row; result["evidence"].append(item)
            result["graph_edges"].append({"type": "observation_selection", "from": {"kind": "observation", "id": oid}, "to": {"kind": "selection", "id": sid}})
            for index, app in enumerate(apps):
                if app["status"] == "valid":
                    result["graph_edges"].append({"type": "application_observation", "from": {"kind": "application", "id": oid, "index": index}, "to": {"kind": "observation", "id": oid}})
        except (Refusal, TypeError, KeyError, ValueError, StopIteration):
            result["findings"].append({"code": "invalid_observation"})
    _relations(value, hist, change, observations, observation_records, result)
    return result


def _support_state(report):
    """Reduce supplied assessment applicability without making a judgment."""
    state = report["status"]
    if state == "applicable":
        return {"supported": "usable", "discrepancy": "discrepancy", "unknown": "unknown"}[report["declared"]["result"]]
    return state


def _summary(causes):
    if not causes:
        return "usable"
    # Keep all causes in the report; the scalar is only a convenience.
    priority = ("invalid", "inconsistent", "historical_unbound", "discrepancy",
                "unavailable", "stale", "unknown", "not_assessed")
    return next((state for state in priority if any(x["state"] == state for x in causes)), "unknown")


def _relations(value, hist, change, observations, observation_records, result):
    findings = result["findings"]
    if hist is None or change is None:
        return
    _, issue, draft = hist["records"]
    known = {"obligations": {x["id"] for x in issue["obligations"]},
             "constraints": {x["id"] for x in issue["shared_constraints"]},
             "conditions": {x["id"] for x in issue["conditions"]},
             "effects": {x["id"] for x in draft["trace"]["effects"]},
             "changes": {x["id"] for x in change["entries"]}}
    for effect in draft["trace"]["effects"]:
        for obligation in effect.get("issue_obligations", []):
            if obligation in known["obligations"]:
                result["graph_edges"].append({"type": "effect_obligation", "from": {"kind": "effect", "id": effect["id"]}, "to": {"kind": "obligations", "id": obligation}})
    for oid, obs in observations.items():
        for index, app in enumerate(obs["applications"]):
            if app["status"] == "valid" and (set(app["scope"]["obligation_ids"]) - known["obligations"] or set(app["scope"]["constraint_ids"]) - known["constraints"]):
                findings.append({"code": "unknown_application_scope", "id": oid, "index": index})

    def selection_causes(oid):
        obs = observations[oid]
        causes = []
        if obs["selection_status"] == "unavailable":
            causes.append(("selection", "unavailable"))
        elif obs["selection_status"] == "selection_invalid":
            causes.append(("selection", "invalid"))
        elif obs["selection_status"] == "changed":
            causes.append(("selection", "stale"))
        selected = next(x for x in result["selections"] if x["id"] == obs["declared"]["selection_id"])
        if selected["reference_changed"]:
            state = _support_state(selected["continuity"])
            if state != "usable":
                causes.append(("continuity", state))
        return causes

    corr = value["correspondence"]
    corr_causes = []
    corr_subject = None
    corr_ids = set()
    corr_valid = False
    try:
        fields(corr, {"effects", "changes", "assessment"})
        if not isinstance(corr["effects"], list) or not isinstance(corr["changes"], list):
            raise Refusal("Invalid mappings.")
        seen_effects = set(); seen_changes = set()
        for row in corr["effects"]:
            fields(row, {"effect_id", "disposition", "change_ids", "observation_ids", "reason"})
            eid = string(row["effect_id"]); string(row["reason"])
            changes = strings(row["change_ids"]); obs = strings(row["observation_ids"])
            if eid in seen_effects or eid not in known["effects"] or set(changes) - known["changes"] or set(obs) - observations.keys() or row["disposition"] not in {"realized", "partial", "not_realized", "not_applicable", "unknown"}:
                raise Refusal("Invalid effect mapping.")
            seen_effects.add(eid); corr_ids.update(obs)
        for row in corr["changes"]:
            fields(row, {"change_id", "effect_ids", "justification"})
            cid = string(row["change_id"]); string(row["justification"]); effects = strings(row["effect_ids"])
            if cid in seen_changes or cid not in known["changes"] or set(effects) - known["effects"]:
                raise Refusal("Invalid change mapping.")
            seen_changes.add(cid)
        missing_effects = sorted(known["effects"] - seen_effects)
        missing_changes = sorted(known["changes"] - seen_changes)
        projection = {oid: {"original": observations[oid]["original_identity"], "target_current_use": observations[oid]["current_use"]} for oid in sorted(corr_ids)}
        corr_subject = identity("correspondence", {"historical": hist["identity"], "change": change["identity"],
                                                    "effects": corr["effects"], "changes": corr["changes"], "observations": projection})
        corr_assessment = assessment(corr["assessment"], corr_subject)
        if missing_effects or missing_changes:
            corr_causes.append({"component": "mappings", "state": "inconsistent"})
        for oid in sorted(corr_ids):
            for component, state in selection_causes(oid):
                corr_causes.append({"component": component, "id": oid, "state": state})
        state = _support_state(corr_assessment)
        if state != "usable":
            corr_causes.append({"component": "correspondence_assessment", "state": state})
        result["correspondence"] = {"status": "incomplete" if missing_effects or missing_changes else "complete",
                                    "missing_effects": missing_effects, "missing_changes": missing_changes,
                                    "assessment": corr_assessment, "declared": {"effects": corr["effects"], "changes": corr["changes"]},
                                    "current_usability": _summary(corr_causes), "causes": corr_causes}
        corr_valid = True
        for row in corr["effects"]:
            for cid in row["change_ids"]:
                result["graph_edges"].append({"type": "effect_change", "from": {"kind": "effect", "id": row["effect_id"]}, "to": {"kind": "change", "id": cid}})
            for oid in row["observation_ids"]:
                result["graph_edges"].append({"type": "effect_observation", "from": {"kind": "effect", "id": row["effect_id"]}, "to": {"kind": "observation", "id": oid}})
        for row in corr["changes"]:
            for eid in row["effect_ids"]:
                result["graph_edges"].append({"type": "change_effect", "from": {"kind": "change", "id": row["change_id"]}, "to": {"kind": "effect", "id": eid}})
    except (Refusal, TypeError, KeyError, ValueError):
        corr_causes.append({"component": "correspondence", "state": "invalid"})
        result["correspondence"] = {"status": "invalid", "declared": corr, "current_usability": "invalid", "causes": corr_causes}
        findings.append({"code": "invalid_correspondence"})

    try:
        claim = fields(value["claim"], {"conclusion", "obligations", "constraints", "conditions", "remainder", "limits"})
        if claim["conclusion"] not in {"complete", "partial", "unresolved"}: raise Refusal("Invalid claim.")
        strings(claim["remainder"]); strings(claim["limits"])
        inconsistent = bool(claim["remainder"]); missing = {}; direct = set(); application_causes = []
        claim_edges = []
        for name in ("obligations", "constraints", "conditions"):
            if not isinstance(claim[name], list): raise Refusal("Invalid dispositions.")
            seen = set()
            for row in claim[name]:
                required = {"id", "disposition", "observation_ids", "reason"} | (set() if name == "conditions" else {"remainder"})
                fields(row, required); rid = string(row["id"]); string(row["reason"])
                if name != "conditions": string(row["remainder"], empty=True)
                allowed = {"satisfied", "not_applicable", "unsatisfied", "unknown"} if name == "conditions" else {"supported", "partial", "discrepancy", "unknown", "outside"}
                if rid in seen or rid not in known[name] or row["disposition"] not in allowed or not isinstance(row["observation_ids"], list):
                    raise Refusal("Invalid disposition.")
                seen.add(rid)
                if row["disposition"] not in ({"satisfied", "not_applicable"} if name == "conditions" else {"supported", "outside"}) or row.get("remainder"):
                    inconsistent = True
                for ref in row["observation_ids"]:
                    fields(ref, {"id", "application"}); oid = string(ref["id"]); index = ref["application"]
                    if oid not in observations or type(index) is not int or not 0 <= index < len(observations[oid]["applications"]):
                        raise Refusal("Invalid observation reference.")
                    app = observations[oid]["applications"][index]
                    if app["status"] != "valid":
                        raise Refusal("Invalid application reference.")
                    direct.add((oid, index))
                    scope = app["scope"]
                    scope_valid = not (set(scope["obligation_ids"]) - known["obligations"] or set(scope["constraint_ids"]) - known["constraints"] or (name == "obligations" and rid not in scope["obligation_ids"]) or (name == "constraints" and rid not in scope["constraint_ids"]))
                    if not scope_valid:
                        application_causes.append({"component": "application_scope", "id": oid, "index": index, "state": "invalid"})
                    for component, state in selection_causes(oid):
                        application_causes.append({"component": "application_" + component, "id": oid, "index": index, "state": state})
                    state = _support_state(app["assessment"])
                    if state != "usable":
                        application_causes.append({"component": "application_assessment", "id": oid, "index": index, "state": state})
                    if scope_valid:
                        claim_edges.append({"type": "disposition_application", "from": {"kind": name, "id": rid}, "to": {"kind": "application", "id": oid, "index": index}})
            missing[name] = sorted(known[name] - seen)
            if missing[name]: inconsistent = True
        if corr_valid and any(row["disposition"] in {"partial", "not_realized", "unknown"} for row in corr["effects"]):
            inconsistent = True
        projection = []
        for oid, index in sorted(direct):
            obs = observations[oid]; app = obs["applications"][index]
            projection.append({"id": oid, "application": index, "original": obs["original_identity"],
                               "target_current_use": obs["current_use"], "scope": app["scope"],
                               "current_conditions": app["current_conditions"], "assessment_subject": app["assessment"]["subject"],
                               "assessment": observation_records[oid]["applications"][index]["assessment"]})
        subject = None if corr_subject is None else identity("claim", {"scope": value["scope"], "historical": hist["identity"],
            "change": change["identity"], "correspondence_subject": corr_subject, "correspondence_assessment": corr["assessment"],
            "applications": projection, "upstream_applicability": value["upstream"]["applicability"], "claim": claim})
        joint = assessment(value["joint_assessment"], subject)
        causes = []
        if hist["bindings"] and not all(hist["bindings"].values()):
            causes.append({"component": "historical_bindings", "state": "historical_unbound"})
        current = result["current_applicability"]
        if current["status"] != "available":
            causes.append({"component": "current_sources", "state": "unavailable"})
        else:
            state = _support_state(current["assessment"])
            if state != "usable": causes.append({"component": "upstream_assessment", "state": state})
        causes.extend(corr_causes); causes.extend(application_causes)
        if any(missing.values()):
            causes.append({"component": "claim_enumeration", "state": "inconsistent"})
        if claim["conclusion"] == "complete" and inconsistent:
            causes.append({"component": "claim_consistency", "state": "inconsistent"})
        usability = _summary(causes)
        joint_causes = list(causes)
        state = _support_state(joint)
        if state != "usable": joint_causes.append({"component": "joint_assessment", "state": state})
        joint["current_usability"] = _summary(joint_causes); joint["causes"] = joint_causes
        result["claim"] = {"status": "inconsistent" if claim["conclusion"] == "complete" and inconsistent else "consistent",
                           "subject": subject, "missing": missing, "joint_assessment": joint, "declared": claim,
                           "current_usability": usability, "causes": causes}
        result["graph_edges"].extend(claim_edges)
        if subject is not None:
            result["graph_edges"].extend([
                {"type": "claim_historical_upstream", "from": {"kind": "claim", "id": subject}, "to": {"kind": "historical_upstream", "id": hist["identity"]}},
                {"type": "claim_change", "from": {"kind": "claim", "id": subject}, "to": {"kind": "git_change", "id": change["identity"]}},
            ])
    except (Refusal, TypeError, KeyError, ValueError):
        result["claim"] = {"status": "invalid", "declared": value["claim"], "current_usability": "invalid",
                           "joint_assessment": assessment(value["joint_assessment"], None)}
        findings.append({"code": "invalid_claim"})
        return
    try:
        decision = value["decision"]
        if decision is not None:
            fields(decision, {"claim_subject", "joint_assessment_subject", "outcome", "authority", "provenance", "reasons", "limits"})
            for key in ("claim_subject", "joint_assessment_subject", "authority", "provenance"): string(decision[key])
            strings(decision["reasons"]); strings(decision["limits"])
            if decision["outcome"] not in {"accepted", "not_accepted", "deferred"}: raise Refusal("Invalid decision.")
            joint_id = None if value["joint_assessment"] is None else identity("joint_assessment", value["joint_assessment"])
            binding = "unavailable" if subject is None else ("matches" if decision["claim_subject"] == subject and decision["joint_assessment_subject"] == joint_id else "stale")
            decision_causes = list(joint_causes)
            if binding != "matches": decision_causes.append({"component": "decision_binding", "state": binding})
            result["decision"] = {"status": binding, "current_usability": _summary(decision_causes), "causes": decision_causes, "declared": decision}
    except (Refusal, TypeError, KeyError, ValueError):
        result["decision"] = {"status": "invalid", "declared": value["decision"], "current_usability": "invalid"}
        findings.append({"code": "invalid_decision"})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only committed-change evidence report.")
    parser.add_argument("operation", choices=["check"]); parser.add_argument("--input", required=True)
    args = parser.parse_args(argv)
    try:
        value = root(parse_json(receipt(args.input)))
    except (Refusal, OSError, ValueError, TypeError):
        print(json.dumps({"error": "invalid_input"})); return 2
    try:
        print(json.dumps(check(value), ensure_ascii=False, indent=2)); return 0
    except Exception:
        print(json.dumps({"error": "internal_failure"})); return 3


if __name__ == "__main__":
    raise SystemExit(main())

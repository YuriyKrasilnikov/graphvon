"""Checked native Issue publication and recovery for a single record writer."""

from __future__ import annotations

from copy import deepcopy
import json
import re
import subprocess
import uuid

from .contracts import Refusal, parse_json
from .issue_check import absolute_path, check, read_text
from .issue_contracts import obj, parse_project, text
from .issue_records import advance, load_record, save_record


class Native:
    def __init__(self, repository: str):
        self.repository = repository

    def get(self, endpoint: str):
        try:
            result = subprocess.run(["gh", "api", "--method", "GET", "--header", "Accept: application/vnd.github+json",
                                     "--header", "X-GitHub-Api-Version: 2026-03-10", endpoint],
                                    capture_output=True, text=True, encoding="utf-8", check=False)
            if result.returncode:
                raise Refusal("Native readback unavailable.")
            return parse_json(result.stdout)
        except (OSError, UnicodeError, ValueError):
            raise Refusal("Native readback unavailable.") from None

    def post(self, payload: dict):
        try:
            result = subprocess.run(["gh", "api", "--method", "POST", "--include", "--header", "Accept: application/vnd.github+json",
                                     "--header", "X-GitHub-Api-Version: 2026-03-10", "--input", "-",
                                     "repos/" + self.repository + "/issues"], input=json.dumps(payload),
                                    capture_output=True, text=True, encoding="utf-8", check=False)
            match = re.match(r"HTTP/\S+ (\d{3})[^\r\n]*\r?\n", result.stdout)
            status = int(match.group(1)) if match else None
            if result.returncode:
                # Only an attributable client rejection is evidence that no creation occurred.
                if status in {400, 401, 403, 404, 405, 410, 422}:
                    return {"kind": "rejected", "status": status}
                return {"kind": "unknown"}
            if status != 201:
                return {"kind": "unknown"}
            parts = re.split(r"\r?\n\r?\n", result.stdout, maxsplit=1)
            if len(parts) != 2:
                return {"kind": "unknown"}
            value = parse_json(parts[1])
            if not isinstance(value, dict):
                return {"kind": "unknown"}
            return {"kind": "response", "value": value}
        except (OSError, UnicodeError, ValueError, Refusal):
            return {"kind": "unknown"}


def identity(value: object, repository: str) -> dict:
    if not isinstance(value, dict) or "pull_request" in value:
        raise Refusal("Native object is not an Issue.")
    if str(value.get("repository_url", "")).casefold() != "https://api.github.com/repos/" + repository:
        raise Refusal("Native Issue repository differs.")
    number, numeric_id = value.get("number"), value.get("id")
    if type(number) is not int or number <= 0 or type(numeric_id) is not int or numeric_id <= 0:
        raise Refusal("Native Issue identity is incomplete.")
    return {"number": number, "id": numeric_id, "node_id": text(value.get("node_id"))}


def _permission(value: object, subject: str) -> dict:
    auth = obj(value, {"source", "subject_sha256", "effect"})
    text(auth["source"])
    if auth["effect"] != "create_issue" or auth["subject_sha256"] != subject:
        raise Refusal("Permission does not bind the assessed publication.")
    return deepcopy(auth)


def _preflight(project, record: dict, auth: object) -> tuple[dict, dict]:
    report = check(project, record, "installed")
    if report["structure"]["status"] != "valid" or report["source_coverage"]["status"] != "consistent_with_assessed_basis":
        raise Refusal("Installed sources or proposal structure are not supported.")
    assessment = report["semantic_assessment"]
    if assessment["applicability"] != "matches_subject":
        raise Refusal("The semantic assessment is not applicable.")
    judgments = assessment["declared_results"]
    if any(judgments[name] != "supported" for name in ("preservation", "readiness", "publication")):
        raise Refusal("The required publication judgments are not supported.")
    if judgments["definition"] == "discrepancy":
        raise Refusal("The assessment identifies a definition discrepancy.")
    if assessment["judgment_context"]["readiness_action"] != "create_issue":
        raise Refusal("The assessment does not cover Issue creation.")
    permission = _permission(auth, report["subject_sha256"])
    payload = deepcopy(report["public_payload"])
    parent = record["candidate"].get("native_parent")
    if parent is not None:
        payload["parent_issue_id"] = parent["id"]
    return {"subject_sha256": report["subject_sha256"], "authorization": permission,
            "payload": payload, "parent": deepcopy(parent)}, report


def _parent_before_send(native: Native, parent: dict | None) -> None:
    if parent is None:
        return
    found = native.get(f"repos/{native.repository}/issues/{parent['number']}")
    if identity(found, native.repository) != parent:
        raise Refusal("The selected native parent identity changed.")


def _save(path, record: dict) -> None:
    advance(record)
    save_record(path, record)


def _result(record: dict, *, persistence: str, observation: dict | None = None) -> dict:
    op = record["operation"]
    return {"status": "unknown" if persistence == "unknown" else op["state"], "record_revision": record["record_revision"],
            "observed_status": op["state"],
            "operation_id": op["id"], "observation": observation,
            "persistence": persistence}


def _observe(native: Native, operation: dict, candidate: dict, evidence: str) -> dict:
    observed = {"candidate": candidate, "resolution_evidence": evidence,
                "object": None, "parent": None, "discrepancies": [], "complete": False}
    try:
        value = native.get(f"repos/{native.repository}/issues/{candidate['number']}")
        actual = identity(value, native.repository)
        observed["object"] = {"identity": actual, "title": value.get("title"), "body": value.get("body")}
        if actual != candidate:
            observed["discrepancies"].append("object_identity")
        if value.get("title") != operation["payload"]["title"] or value.get("body") != operation["payload"]["body"]:
            observed["discrepancies"].append("object_content")
    except (Refusal, KeyError, TypeError):
        observed["discrepancies"].append("object_unavailable")
    expected = operation["parent"]
    if expected is None:
        observed["parent"] = {"required": False}
    else:
        try:
            relation = native.get(f"repos/{native.repository}/issues/{candidate['number']}/parent")
            actual_parent = identity(relation, native.repository)
            observed["parent"] = {"identity": actual_parent}
            if actual_parent != expected:
                observed["discrepancies"].append("parent_identity")
        except (Refusal, KeyError, TypeError):
            observed["discrepancies"].append("parent_unavailable")
    observed["complete"] = not observed["discrepancies"]
    return observed


def create(request: dict, native_factory=Native) -> dict:
    request = obj(request, {"version", "project_basis", "proposal", "expected_record_revision", "authorization"}, {"owner_settled", "rejection_resolution"})
    if type(request["version"]) is not int or request["version"] != 1:
        raise Refusal("Unsupported publication request.")
    project = parse_project(parse_json(read_text(absolute_path(request["project_basis"]))))
    path = absolute_path(request["proposal"])
    record = load_record(path, request["expected_record_revision"])
    operation = record.get("operation")
    rejected = operation is not None and operation["state"] == "rejected"
    if operation is not None and operation["state"] not in {"prepared", "rejected"}:
        raise Refusal("This operation cannot send again; reconcile the existing state.")
    if operation is not None and request.get("owner_settled") is not True:
        raise Refusal("Continuation requires settled prior ownership.")
    if rejected:
        text(request.get("rejection_resolution"))
    elif "rejection_resolution" in request:
        raise Refusal("Rejection resolution requires a rejected operation.")
    intent, _ = _preflight(project, record, request["authorization"])
    native = native_factory(project.repository)
    _parent_before_send(native, intent["parent"])
    if operation is None or rejected:
        history = [] if operation is None else [{"operation": deepcopy(operation), "resolution_evidence": request["rejection_resolution"]}]
        operation = {"id": str(uuid.uuid4()), "state": "prepared", "repository": project.repository, **intent,
                     "observations": [], "prior_rejections": history}
        record["operation"] = operation
        _save(path, record)
    elif operation["repository"] != project.repository or any(operation[key] != intent[key] for key in intent):
        raise Refusal("Prepared intent or permission changed; reassessment is required.")
    # Re-observe all installed sources and the parent after preparation, before Sending.
    current, _ = _preflight(project, record, request["authorization"])
    if current != intent:
        raise Refusal("The prepared publication basis changed.")
    _parent_before_send(native, intent["parent"])
    operation["state"] = "sending"
    _save(path, record)
    response = native.post(operation["payload"])
    if response["kind"] == "rejected":
        operation["state"] = "rejected"
        observation = {"rejection_status": response["status"]}
    elif response["kind"] == "response":
        try:
            candidate = identity(response["value"], project.repository)
        except Refusal:
            observation = {"unknown": "creation response identity unavailable"}
        else:
            evidence = "identity from creation response"
            observation = {"candidate": candidate, "resolution_evidence": evidence,
                           "object": None, "parent": None, "discrepancies": ["readback_pending"], "complete": False}
            operation["state"] = "observed"
            operation["observations"].append(observation)
            try:
                _save(path, record)
            except Refusal:
                return _result(record, persistence="unknown", observation=observation)
            observation = _observe(native, operation, candidate, evidence)
            operation["state"] = "confirmed" if observation["complete"] else "observed"
    else:
        observation = {"unknown": "creation outcome unavailable"}
    operation["observations"].append(observation)
    try:
        _save(path, record)
        return _result(record, persistence="saved", observation=observation)
    except Refusal:
        return _result(record, persistence="unknown", observation=observation)


def reconcile(request: dict, native_factory=Native) -> dict:
    request = obj(request, {"version", "proposal", "expected_record_revision"}, {"candidate", "resolution_evidence"})
    if type(request["version"]) is not int or request["version"] != 1:
        raise Refusal("Unsupported reconciliation request.")
    path = absolute_path(request["proposal"])
    record = load_record(path, request["expected_record_revision"])
    operation = record.get("operation")
    if operation is None or operation["state"] not in {"sending", "observed", "confirmed"}:
        raise Refusal("No uncertain or observed operation is available to reconcile.")
    candidate = request.get("candidate")
    evidence = request.get("resolution_evidence")
    if candidate is None:
        if evidence is not None:
            raise Refusal("Resolution evidence requires a native candidate.")
        for prior in reversed(operation["observations"]):
            if "candidate" in prior:
                candidate = prior["candidate"]
                evidence = prior["resolution_evidence"]
                break
    else:
        text(evidence)
    if candidate is None:
        return _result(record, persistence="unchanged", observation={"unknown": "no attributed native identity"})
    candidate = obj(candidate, {"number", "id", "node_id"})
    if any(type(candidate[key]) is not int or candidate[key] <= 0 for key in ("number", "id")):
        raise Refusal("Invalid native candidate identity.")
    text(candidate["node_id"])
    observed = _observe(native_factory(operation["repository"]), operation, candidate, evidence)
    operation["observations"].append(observed)
    operation["state"] = "confirmed" if observed["complete"] else "observed"
    try:
        _save(path, record)
        return _result(record, persistence="saved", observation=observed)
    except Refusal:
        return _result(record, persistence="unknown", observation=observed)

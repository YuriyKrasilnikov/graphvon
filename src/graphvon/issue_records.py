"""Private ordinary-file persistence for one coordinator-owned writer.

This is not a lock; callers settle prior ownership before using the record.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile
import uuid

from .contracts import Refusal, parse_json, repository_name
from .issue_contracts import digest, obj, parse_proposal, text


def load_record(path: Path, revision: str) -> dict:
    text(revision)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise Refusal("The private record is not an ordinary file.")
            with os.fdopen(fd, encoding="utf-8", closefd=False) as stream:
                record = parse_proposal(parse_json(stream.read()))
        finally:
            os.close(fd)
    except (OSError, UnicodeError, ValueError):
        raise Refusal("The private record cannot be read.") from None
    if record["record_revision"] != revision:
        raise Refusal("The private record revision changed.")
    validate_operation(record.get("operation"))
    return record


def validate_operation(operation: object) -> None:
    if operation is None:
        return
    operation = obj(operation, {"id", "state", "repository", "subject_sha256", "authorization", "payload", "parent", "observations", "prior_rejections"})
    text(operation["id"])
    if repository_name(operation["repository"]) != operation["repository"]:
        raise Refusal("Invalid operation repository.")
    digest(operation["subject_sha256"])
    if operation["state"] not in {"prepared", "sending", "rejected", "observed", "confirmed"}:
        raise Refusal("Invalid publication state.")
    auth = obj(operation["authorization"], {"source", "subject_sha256", "effect"})
    for key in auth:
        text(auth[key])
    if auth["effect"] != "create_issue" or auth["subject_sha256"] != operation["subject_sha256"]:
        raise Refusal("The stored permission does not bind the operation.")
    payload = obj(operation["payload"], {"title", "body"}, {"parent_issue_id"})
    text(payload["title"])
    text(payload["body"], empty=True)
    if "parent_issue_id" in payload and (type(payload["parent_issue_id"]) is not int or payload["parent_issue_id"] <= 0):
        raise Refusal("Invalid parent identifier.")
    parent = operation["parent"]
    if parent is not None:
        parent = obj(parent, {"number", "id", "node_id"})
        if any(type(parent[k]) is not int or parent[k] <= 0 for k in ("number", "id")):
            raise Refusal("Invalid parent identity.")
        text(parent["node_id"])
        if payload.get("parent_issue_id") != parent["id"]:
            raise Refusal("Parent and payload disagree.")
    elif "parent_issue_id" in payload:
        raise Refusal("Parent and payload disagree.")
    observations = operation["observations"]
    if not isinstance(observations, list) or not all(isinstance(item, dict) for item in observations):
        raise Refusal("Invalid publication observations.")
    for item in observations:
        if set(item) == {"unknown"}:
            text(item["unknown"])
        elif set(item) == {"rejection_status"}:
            if item["rejection_status"] not in {400, 401, 403, 404, 405, 410, 422}:
                raise Refusal("Invalid rejection observation.")
        else:
            obj(item, {"candidate", "resolution_evidence", "object", "parent", "discrepancies", "complete"})
            candidate = obj(item["candidate"], {"number", "id", "node_id"})
            if any(type(candidate[k]) is not int or candidate[k] <= 0 for k in ("number", "id")):
                raise Refusal("Invalid observed Issue identity.")
            text(candidate["node_id"])
            text(item["resolution_evidence"])
            if not isinstance(item["discrepancies"], list) or not all(isinstance(x, str) and x for x in item["discrepancies"]):
                raise Refusal("Invalid observation discrepancies.")
            if type(item["complete"]) is not bool or item["complete"] != (not item["discrepancies"]):
                raise Refusal("Contradictory observation completeness.")
            if item["object"] is not None and not isinstance(item["object"], dict):
                raise Refusal("Invalid object observation.")
            if item["parent"] is not None and not isinstance(item["parent"], dict):
                raise Refusal("Invalid parent observation.")
            if item["complete"]:
                observed_object = obj(item["object"], {"identity", "title", "body"})
                if (observed_object["identity"] != candidate or observed_object["title"] != payload["title"]
                        or observed_object["body"] != payload["body"]):
                    raise Refusal("Complete observation does not match the intended object.")
                expected_parent = ({"required": False} if parent is None else {"identity": parent})
                if item["parent"] != expected_parent:
                    raise Refusal("Complete observation does not match the selected parent.")
    if operation["state"] == "prepared" and observations:
        raise Refusal("A prepared operation cannot have transmission observations.")
    if operation["state"] == "rejected" and (not observations or "rejection_status" not in observations[-1]):
        raise Refusal("Rejected state requires an attributable rejection observation.")
    if operation["state"] == "confirmed" and (not observations or observations[-1].get("complete") is not True):
        raise Refusal("Confirmed state requires a complete native observation.")
    if not isinstance(operation["prior_rejections"], list):
        raise Refusal("Invalid prior rejection history.")
    for previous in operation["prior_rejections"]:
        previous = obj(previous, {"operation", "resolution_evidence"})
        text(previous["resolution_evidence"])
        validate_operation(previous["operation"])
        if previous["operation"]["state"] != "rejected":
            raise Refusal("Only rejected operations can precede a new attempt.")


def save_record(path: Path, record: dict) -> str:
    """Replace and sync a record; an error never claims the write is durable."""
    validate_operation(record.get("operation"))
    parse_proposal(record)
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            raise Refusal("The private record is not an ordinary file.")
        parent = path.parent
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        temporary = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".graphvon-record-", dir=parent)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
            os.fsync(directory)
        finally:
            if temporary is not None:
                os.unlink(temporary)
            os.close(directory)
    except OSError:
        raise Refusal("Private record persistence failed; its durable state is unknown.") from None
    return record["record_revision"]


def advance(record: dict) -> None:
    record["record_revision"] = str(uuid.uuid4())

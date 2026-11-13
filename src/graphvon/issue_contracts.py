"""Contracts for read-only Issue checks, without inferring semantic authority."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re
from typing import Any

import yaml

from .contracts import Refusal, content_digest, repository_name


def obj(value: Any, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or required - value.keys() or value.keys() - required - optional:
        raise Refusal("Invalid proposal-check object fields.")
    return value


def text(value: Any, *, empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value or (not empty and not value.strip()):
        raise Refusal("Expected proposal-check text.")
    return value


def strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise Refusal("Expected a list of proposal-check references.")
    result = tuple(text(item) for item in value)
    if len(set(result)) != len(result):
        raise Refusal("Duplicate proposal-check references.")
    return result


def digest(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise Refusal("Expected a content fingerprint.")
    return value


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def relative_path(value: Any) -> str:
    value = text(value)
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or not path.parts or ".." in path.parts or "\\" in value:
        raise Refusal("Expected a repository-relative source path.")
    return value


class _UniqueSafeLoader(yaml.SafeLoader):
    """Keep safe YAML construction and reject ambiguous duplicate mappings."""


def _mapping(loader: _UniqueSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise Refusal("The Issue Form contains ambiguous mapping keys.")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    required: bool
    default: str
    render: str | None


@dataclass(frozen=True)
class Form:
    fields: tuple[Field, ...]
    title: str


def load_form(source: str) -> Form:
    try:
        data = obj(yaml.load(source, Loader=_UniqueSafeLoader), {"name", "description", "body"}, {"title"})
        text(data["name"])
        text(data["description"])
        if not isinstance(data["body"], list) or not data["body"]:
            raise Refusal("The Issue Form requires supported fields.")
        fields = []
        ids = set()
        for row in data["body"]:
            row = obj(row, {"type", "attributes"}, {"id", "validations"})
            if row["type"] == "markdown":
                if set(row) != {"type", "attributes"}:
                    raise Refusal("Unsupported Issue Form instruction fields.")
                text(obj(row["attributes"], {"value"})["value"])
                continue
            if row["type"] != "textarea" or "id" not in row:
                raise Refusal("Unsupported Issue Form field type.")
            key = text(row["id"])
            if not re.fullmatch(r"[A-Za-z0-9_-]+", key):
                raise Refusal("Issue Form field identifiers require letters, digits, hyphens or underscores.")
            if key in ids:
                raise Refusal("The Issue Form has duplicate field identifiers.")
            ids.add(key)
            attrs = obj(row["attributes"], {"label"}, {"description", "placeholder", "value", "render"})
            for value in attrs.values():
                text(value, empty=True)
            label = text(attrs["label"])
            if "\n" in label or "\r" in label:
                raise Refusal("Issue Form labels must be single-line text.")
            validations = obj(row.get("validations", {}), set(), {"required"})
            required = validations.get("required", False)
            if type(required) is not bool:
                raise Refusal("Invalid Issue Form required-field declaration.")
            render = attrs.get("render")
            if render is not None and (not render or any(c in render for c in "\r\n`")):
                raise Refusal("Invalid Issue Form rendering language.")
            fields.append(Field(key, label, required, attrs.get("value", ""), render))
        if not fields:
            raise Refusal("The Issue Form has no supported input fields.")
        return Form(tuple(fields), text(data.get("title", ""), empty=True))
    except (yaml.YAMLError, RecursionError, TypeError, ValueError):
        raise Refusal("The Issue Form could not be read safely.") from None


def render(form: Form, title: str, values: dict) -> tuple[dict | None, list[str]]:
    if not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()):
        raise Refusal("Issue field values must be a text mapping.")
    findings = []
    if set(values) - {field.id for field in form.fields}:
        findings.append("unknown_field")
    title = title if title.strip() else form.title
    if not title.strip():
        findings.append("missing_title")
    parts = []
    for field in form.fields:
        value = text(values.get(field.id, field.default), empty=True)
        if not value.strip():
            if field.required:
                findings.append("missing_required_field")
            continue
        if field.render:
            fence = "`" * max(3, 1 + max((len(x) for x in re.findall(r"`+", value)), default=0))
            value = f"{fence}{field.render}\n{value}\n{fence}"
        parts.append(f"### {field.label}\n\n{value}")
    return (None if findings else {"title": title, "body": "\n\n".join(parts) + "\n"}), findings


@dataclass(frozen=True)
class Source:
    key: str
    kind: str
    location: str | int
    sha256: str
    applicability: str
    basis: str


@dataclass(frozen=True)
class ProjectBasis:
    raw: dict
    root: str
    repository: str
    repository_id: str
    entry_source: str
    entry_fragment: str
    sources: tuple[Source, ...]
    templates: tuple[str, ...]
    scope: str


def project_subject(data: dict) -> str:
    """Identify the assessed projection; this is not proof of its authority."""
    return content_digest({key: value for key, value in data.items() if key != "assessment"})


def parse_project(data: Any) -> ProjectBasis:
    data = obj(data, {"version", "root", "repository", "canonical_entry", "sources", "allowed_templates", "scope", "assessment"})
    if type(data["version"]) is not int or data["version"] != 1:
        raise Refusal("Unsupported project-basis format.")
    repo = obj(data["repository"], {"name", "id"})
    entry = obj(data["canonical_entry"], {"source", "fragment"})
    if not isinstance(data["sources"], list) or not data["sources"]:
        raise Refusal("A project basis requires explicit sources.")
    sources = []
    keys = set()
    for row in data["sources"]:
        row = obj(row, {"key", "kind", "location", "sha256", "applicability", "basis", "owner", "status"})
        key = text(row["key"])
        if key in keys:
            raise Refusal("Duplicate source identities.")
        keys.add(key)
        kind = text(row["kind"])
        if kind not in {"repository_file", "local_file", "github_issue"}:
            raise Refusal("Unsupported project source kind.")
        location = row["location"]
        if kind == "github_issue":
            if type(location) is not int or location <= 0:
                raise Refusal("Invalid native Issue source.")
        elif kind == "repository_file":
            location = relative_path(location)
        else:
            location = text(location)
        applicability = row["applicability"]
        if applicability not in {"required", "not_applicable", "unknown"}:
            raise Refusal("Invalid source applicability.")
        text(row["owner"])
        text(row["status"])
        sources.append(Source(key, kind, location, digest(row["sha256"]), applicability, text(row["basis"])))
    entry_key = text(entry["source"])
    templates = strings(data["allowed_templates"])
    if entry_key not in keys or not templates or set(templates) - keys:
        raise Refusal("The canonical entry and templates must identify declared sources.")
    by_key = {source.key: source for source in sources}
    if by_key[entry_key].kind != "repository_file" or by_key[entry_key].applicability != "required":
        raise Refusal("The canonical entry must be an applicable repository file.")
    if any(by_key[key].kind != "repository_file" for key in templates):
        raise Refusal("Issue Forms must be declared repository files.")
    assessment = obj(data["assessment"], {"subject_sha256", "provenance", "scope", "conclusion", "limits"})
    digest(assessment["subject_sha256"])
    text(assessment["provenance"])
    text(assessment["scope"])
    strings(assessment["limits"])
    if assessment["conclusion"] not in {"supported", "discrepancy", "unknown"}:
        raise Refusal("Invalid project-basis assessment.")
    return ProjectBasis(data, text(data["root"]), repository_name(repo["name"]), text(repo["id"]),
                        entry_key, text(entry["fragment"]), tuple(sources), templates, text(data["scope"]))


def parse_proposal(data: Any) -> dict:
    data = obj(data, {"schema_version", "artifact_id", "record_revision", "candidate", "trace", "assessment"},
               {"operation", "observation"})
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise Refusal("Unsupported proposal format.")
    text(data["artifact_id"])
    text(data["record_revision"])
    candidate = obj(data["candidate"], {"template", "title", "fields", "relationships"}, {"native_parent"})
    text(candidate["template"])
    text(candidate["title"], empty=True)
    if not isinstance(candidate["fields"], dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in candidate["fields"].items()):
        raise Refusal("Issue field values must be a text mapping.")
    strings(candidate["relationships"])
    if "native_parent" in candidate:
        parent = obj(candidate["native_parent"], {"number", "id", "node_id"})
        if type(parent["number"]) is not int or parent["number"] <= 0 or type(parent["id"]) is not int or parent["id"] <= 0:
            raise Refusal("Invalid native parent identity.")
        text(parent["node_id"])
    trace = obj(data["trace"], {"source_keys", "obligations", "remaining", "unknowns", "scope", "conditions", "next_action"})
    for name in ("source_keys", "remaining", "unknowns", "conditions"):
        strings(trace[name])
    text(trace["scope"])
    text(trace["next_action"])
    if not isinstance(trace["obligations"], list):
        raise Refusal("Expected traced obligations.")
    ids = set()
    for obligation in trace["obligations"]:
        obligation = obj(obligation, {"id", "sources", "fields", "coverage", "rationale"}, {"decision_sources"})
        identity = text(obligation["id"])
        if identity in ids:
            raise Refusal("Duplicate traced obligation identities.")
        ids.add(identity)
        strings(obligation["sources"])
        strings(obligation["fields"])
        strings(obligation.get("decision_sources", []))
        text(obligation["rationale"])
        if obligation["coverage"] not in {"covered", "partial", "outside", "unknown"}:
            raise Refusal("Invalid declared obligation coverage.")
    if data["assessment"] is not None:
        assessment = obj(data["assessment"], {"subject_sha256", "provenance", "scope", "preservation", "definition", "readiness", "publication", "limits"})
        digest(assessment["subject_sha256"])
        text(assessment["provenance"])
        text(assessment["scope"])
        strings(assessment["limits"])
        for name in ("preservation", "definition", "readiness", "publication"):
            finding = obj(assessment[name], {"result", "reasons", "action"} if name == "readiness" else {"result", "reasons"})
            if finding["result"] not in {"supported", "discrepancy", "unknown", "not_assessed"}:
                raise Refusal("Invalid declared semantic result.")
            strings(finding["reasons"])
            if name == "readiness":
                text(finding["action"])
    return data


def proposal_subject(project: ProjectBasis, proposal: dict, payload: dict, observed_sources: dict[str, str]) -> str:
    """Exclude record revision and operation observations from semantic identity."""
    return content_digest({"project": project_subject(project.raw), "sources": observed_sources,
                           "candidate": proposal["candidate"], "public_payload": payload,
                           "trace": proposal["trace"]})

"""Canonical version-1 assignment data and validation.

An assignment records an existing admission. Its fields do not independently
establish authority, semantic relevance, reviewer independence, or a lock.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any


class Refusal(Exception):
    """An expected failure with a message safe to return to the caller."""


OPERATIONS = frozenset({"add", "update", "delete", "move_from", "move_to", "mkdir"})
DISCUSSIONS = (
    "issue_comments",
    "pull_request_issue_comments",
    "pull_request_reviews",
    "pull_request_review_comments",
)


def _text(value: Any, field: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()) or "\x00" in value:
        raise Refusal(f"Invalid {field}.")
    return value


def _integer(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise Refusal(f"Invalid {field}.")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise Refusal(f"Invalid {field}.")
    return value.lower()


def _object(value: Any, keys: set[str], field: str, optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or set(value) - keys - optional or keys - set(value):
        raise Refusal(f"Invalid {field} fields.")
    return value


def repository_name(value: Any) -> str:
    value = _text(value, "repository name")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", value):
        raise Refusal("Invalid repository name.")
    if value.split("/")[1] in {".", ".."}:
        raise Refusal("Invalid repository name.")
    return value.casefold()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parse_json(text: str) -> Any:
    def pairs(values: list[tuple[str, Any]]) -> dict:
        result = {}
        for key, value in values:
            if key in result:
                raise Refusal("JSON contains duplicate fields.")
            result[key] = value
        return result

    def constant(_: str) -> None:
        raise Refusal("JSON contains a non-finite number.")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError, RecursionError) as error:
        raise Refusal("Invalid JSON record.") from error


@dataclass(frozen=True)
class Grant:
    operation: str
    path: str
    replace_existing: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or self.operation not in OPERATIONS:
            raise Refusal("Unsupported grant operation.")
        value = _text(self.path, "grant path")
        path = PurePosixPath(value)
        if path.is_absolute() or not path.parts or str(path) != value or ".." in path.parts or any(c in value for c in "\\\r\n"):
            raise Refusal("Grant paths must be canonical repository-relative POSIX paths.")
        if type(self.replace_existing) is not bool:
            raise Refusal("Invalid replacement permission.")
        if self.replace_existing and self.operation not in {"add", "move_to"}:
            raise Refusal("Replacement permission applies only to add or move destinations.")


def _grants(value: Any) -> tuple[Grant, ...]:
    if not isinstance(value, list) or not value:
        raise Refusal("An assignment must declare its exact grants.")
    result = []
    seen = set()
    for item in value:
        item = _object(item, {"operation", "path"}, "grant", {"replace_existing"})
        grant = Grant(item["operation"], item["path"], item.get("replace_existing", False))
        key = (grant.operation, grant.path)
        if key in seen:
            raise Refusal("Duplicate or contradictory grants.")
        seen.add(key)
        result.append(grant)
    return tuple(result)


@dataclass(frozen=True)
class Repository:
    name: str
    id: str
    remote: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", repository_name(self.name))
        _text(self.id, "native repository identity")
        remote = _text(self.remote, "Git remote")
        if remote.startswith("-") or any(c.isspace() for c in remote):
            raise Refusal("Invalid Git remote.")


@dataclass(frozen=True)
class BodyBasis:
    number: int
    id: str
    state: str
    content_sha256: str


@dataclass(frozen=True)
class ProposalBasis(BodyBasis):
    draft: bool
    head_repository_id: str
    head_ref: str
    base_repository_id: str
    base_ref: str


@dataclass(frozen=True)
class DiscussionRecord:
    id: str
    updated_at: str | None
    submitted_at: str | None
    content_sha256: str


@dataclass(frozen=True)
class PublicRepository:
    name: str
    id: str


@dataclass(frozen=True)
class DiscussionBasis:
    issue_comments: tuple[DiscussionRecord, ...]
    pull_request_issue_comments: tuple[DiscussionRecord, ...]
    pull_request_reviews: tuple[DiscussionRecord, ...]
    pull_request_review_comments: tuple[DiscussionRecord, ...]


@dataclass(frozen=True)
class Basis:
    complete: bool
    repository: PublicRepository
    issue: BodyBasis
    proposal: ProposalBasis
    discussions: DiscussionBasis

    def to_dict(self) -> dict:
        return json.loads(canonical_json(asdict(self)))


def parse_basis(value: Any) -> Basis:
    value = _object(value, {"complete", "repository", "issue", "proposal", "discussions"}, "source basis")
    if value["complete"] is not True:
        raise Refusal("Source observation is incomplete.")
    repo = _object(value["repository"], {"name", "id"}, "basis repository")
    repository = PublicRepository(repository_name(repo["name"]), _text(repo["id"], "native repository identity"))

    def body(item: Any, proposal: bool) -> BodyBasis:
        keys = {"number", "id", "state", "content_sha256"}
        if proposal:
            keys |= {"draft", "head_repository_id", "head_ref", "base_repository_id", "base_ref"}
        item = _object(item, keys, "native body basis")
        if not isinstance(item["state"], str) or item["state"] not in {"open", "closed"}:
            raise Refusal("Invalid native lifecycle state.")
        values = dict(number=_integer(item["number"], "native number"), id=_text(item["id"], "native identity"),
                      state=item["state"], content_sha256=_digest(item["content_sha256"], "native content digest"))
        if not proposal:
            return BodyBasis(**values)
        if type(item["draft"]) is not bool:
            raise Refusal("Invalid Draft state.")
        for field in ("head_repository_id", "head_ref", "base_repository_id", "base_ref"):
            values[field] = _text(item[field], "proposal branch identity")
        return ProposalBasis(**values, draft=item["draft"])

    discussion_values = _object(value["discussions"], set(DISCUSSIONS), "discussion coverage")
    collections = {}
    for name in DISCUSSIONS:
        records = discussion_values[name]
        if not isinstance(records, list):
            raise Refusal("Invalid discussion collection.")
        parsed = []
        seen = set()
        for item in records:
            item = _object(item, {"id", "updated_at", "submitted_at", "content_sha256"}, "discussion record")
            native_id = _text(item["id"], "discussion identity")
            if native_id in seen:
                raise Refusal("Duplicate discussion identity.")
            seen.add(native_id)
            timestamps = {}
            for field in ("updated_at", "submitted_at"):
                timestamps[field] = None if item[field] is None else _text(item[field], "discussion timestamp")
            parsed.append(DiscussionRecord(native_id, content_sha256=_digest(item["content_sha256"], "discussion digest"), **timestamps))
        collections[name] = tuple(sorted(parsed, key=lambda row: row.id))
    return Basis(True, repository, body(value["issue"], False), body(value["proposal"], True), DiscussionBasis(**collections))


def scope_digest(kind: str, effect: str, grants: tuple[Grant, ...] | list[Grant]) -> str:
    """Bind the declared scope internally; this hash is not authority evidence."""
    if kind not in ("preparation", "implementation"):
        raise Refusal("Invalid assignment kind.")
    _text(effect, "assigned effect")
    if not isinstance(grants, (tuple, list)) or not grants or not all(isinstance(g, Grant) for g in grants):
        raise Refusal("Invalid assignment grants.")
    if len({(g.operation, g.path) for g in grants}) != len(grants):
        raise Refusal("Duplicate or contradictory grants.")
    return content_digest({"kind": kind, "effect": effect,
                           "grants": [asdict(g) for g in sorted(grants, key=lambda g: (g.operation, g.path))]})


@dataclass(frozen=True)
class Admission:
    reference: str
    sha256: str
    scope_sha256: str

    def __post_init__(self) -> None:
        _text(self.reference, "admission reference")
        object.__setattr__(self, "sha256", _digest(self.sha256, "admission digest"))
        object.__setattr__(self, "scope_sha256", _digest(self.scope_sha256, "admission scope digest"))


@dataclass(frozen=True)
class Review:
    reference: str
    sha256: str
    requirement_sha256: str
    proposal_sha256: str
    scope_sha256: str
    provenance: str
    conclusion: str
    limits: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.reference, "review reference")
        _text(self.provenance, "review provenance")
        for field in ("sha256", "requirement_sha256", "proposal_sha256", "scope_sha256"):
            object.__setattr__(self, field, _digest(getattr(self, field), "review digest"))
        if self.conclusion != "proceed":
            raise Refusal("Review does not support continuation.")
        if not isinstance(self.limits, tuple):
            raise Refusal("Invalid review limitations.")
        for limit in self.limits:
            _text(limit, "review limitation")


@dataclass(frozen=True)
class Implementation:
    issue_number: int
    pull_number: int
    basis: Basis
    review: Review


@dataclass(frozen=True)
class Context:
    root: Path
    kind: str
    grants: tuple[Grant, ...]
    owner: str
    generation: str
    repository: Repository
    effect: str
    admission: Admission
    implementation: Implementation | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path) or not self.root.is_absolute() or ".." in self.root.parts:
            raise Refusal("Checkout root must be an absolute path.")
        _text(self.owner, "assignment owner")
        _text(self.generation, "assignment generation")
        if not isinstance(self.grants, tuple) or not isinstance(self.repository, Repository) or not isinstance(self.admission, Admission):
            raise Refusal("Invalid typed assignment context.")
        scope = scope_digest(self.kind, self.effect, self.grants)
        if self.admission.scope_sha256 != scope:
            raise Refusal("Assigned scope differs from its admission.")
        if self.kind == "preparation":
            if self.implementation is not None:
                raise Refusal("Preparation must not contain implementation evidence.")
            return
        implementation = self.implementation
        if not isinstance(implementation, Implementation) or not isinstance(implementation.basis, Basis) or not isinstance(implementation.review, Review):
            raise Refusal("Implementation evidence is required.")
        basis, review = implementation.basis, implementation.review
        # Revalidate direct typed construction as well as JSON-loaded contexts.
        basis = parse_basis(basis.to_dict())
        if basis.repository != PublicRepository(self.repository.name, self.repository.id):
            raise Refusal("Implementation repository identity differs from the assignment.")
        if basis.issue.number != _integer(implementation.issue_number, "Issue number") or basis.proposal.number != _integer(implementation.pull_number, "PR number"):
            raise Refusal("Implementation object numbers differ from their basis.")
        if basis.proposal.base_repository_id != self.repository.id:
            raise Refusal("Proposal base repository differs from the assignment.")
        if basis.issue.state != "open" or basis.proposal.state != "open" or not basis.proposal.draft:
            raise Refusal("Implementation requires an open Issue and open Draft proposal.")
        if (review.requirement_sha256 != basis.issue.content_sha256
                or review.proposal_sha256 != basis.proposal.content_sha256
                or review.scope_sha256 != scope):
            raise Refusal("Review basis or scope differs from the assignment.")


def context_from_dict(value: Any) -> Context:
    """Parse the only version-1 JSON shape; unknown fields are refused.

    Common keys: version, kind, root, repository, owner, generation, effect,
    grants, admission. Repository has name/id/remote; admission has
    reference/sha256/scope_sha256. Preparation omits implementation entirely.
    Implementation adds issue_number/pull_number/basis/review under its own key.
    Review has reference/sha256/requirement_sha256/proposal_sha256/scope_sha256,
    provenance/conclusion/limits. Basis is defined by parse_basis and its frozen
    data types. Opaque references describe existing evidence, not a new approval
    artifact. Actual private record location is not part of this schema.
    """
    common = {"version", "kind", "root", "repository", "owner", "generation", "effect", "grants", "admission"}
    value = _object(value, common, "assignment", {"implementation"})
    if type(value["version"]) is not int or value["version"] != 1:
        raise Refusal("Unsupported assignment schema version.")
    repo = _object(value["repository"], {"name", "id", "remote"}, "repository")
    admission = _object(value["admission"], {"reference", "sha256", "scope_sha256"}, "admission")
    implementation = None
    if value["kind"] == "preparation" and "implementation" in value:
        raise Refusal("Preparation must omit implementation evidence.")
    if "implementation" in value:
        item = _object(value["implementation"], {"issue_number", "pull_number", "basis", "review"}, "implementation")
        review = _object(item["review"], {"reference", "sha256", "requirement_sha256", "proposal_sha256", "scope_sha256", "provenance", "conclusion", "limits"}, "review")
        if not isinstance(review["limits"], list):
            raise Refusal("Invalid review limitations.")
        implementation = Implementation(item["issue_number"], item["pull_number"], parse_basis(item["basis"]),
                                        Review(**{**review, "limits": tuple(review["limits"])}))
    return Context(Path(_text(value["root"], "checkout root")), value["kind"], _grants(value["grants"]),
                   value["owner"], value["generation"], Repository(**repo), value["effect"],
                   Admission(**admission), implementation)

"""Read native GitHub sources without granting semantic authority.

Two equal complete passes are a bounded observation, not an atomic GitHub
snapshot. No cache or incomplete-read fallback is used.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import time
from typing import Any
from urllib.parse import urlsplit

from .contracts import (
    Context, DISCUSSIONS, Refusal, content_digest, context_from_dict,
    parse_basis, parse_json, repository_name,
)


def load_context(path: str | Path) -> Context:
    """Read an ordinary file at the exact locator; refuse non-regular inputs."""
    try:
        locator = Path(path)
        if not locator.is_absolute():
            raise Refusal("The context locator must be absolute.")
        descriptor = os.open(locator, os.O_RDONLY | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise Refusal("The context record must be a regular file.")
            with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as stream:
                text = stream.read()
        finally:
            os.close(descriptor)
        return context_from_dict(parse_json(text))
    except Refusal:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        raise Refusal("The context record could not be read or validated.") from None


def _remaining(deadline: float) -> float:
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise Refusal("Invalid read deadline.")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Refusal("Source checking reached its deadline.")
    return remaining


def _run(arguments: list[str], deadline: float, operation: str) -> str:
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8",
                                timeout=_remaining(deadline), check=False)
    except subprocess.TimeoutExpired:
        raise Refusal(f"{operation} reached its deadline.") from None
    except (OSError, UnicodeError):
        raise Refusal(f"{operation} could not run.") from None
    _remaining(deadline)
    if result.returncode != 0:
        # stderr may contain credentials or a private local locator.
        raise Refusal(f"{operation} failed; no complete observation is available.")
    return result.stdout


def _pages(text: str, paginated: bool) -> Any:
    """Accept combined gh arrays or successive arrays; JSON count is not page count."""
    decoder = json.JSONDecoder()
    pages = []
    offset = 0
    try:
        while offset < len(text):
            while offset < len(text) and text[offset].isspace():
                offset += 1
            if offset == len(text):
                break
            _, end = decoder.raw_decode(text, offset)
            pages.append(parse_json(text[offset:end]))
            offset = end
    except (ValueError, TypeError, RecursionError):
        raise Refusal("GitHub returned invalid JSON.") from None
    if not pages:
        raise Refusal("GitHub returned an empty response.")
    if paginated:
        if not all(isinstance(page, list) for page in pages):
            raise Refusal("GitHub pagination returned an unexpected shape.")
        rows = [item for page in pages for item in page]
        identities = [_native_id(item) for item in rows]
        if len({item[0] for item in identities}) != len(rows) or len({item[1] for item in identities}) != len(rows):
            raise Refusal("GitHub pagination returned duplicate identities.")
        return rows
    if len(pages) != 1 or not isinstance(pages[0], dict):
        raise Refusal("GitHub returned an unexpected resource shape.")
    return pages[0]


def _read(endpoint: str, paginated: bool, deadline: float) -> Any:
    arguments = ["gh", "api", "--method", "GET", "--header", "Accept: application/vnd.github+json",
                 "--header", "X-GitHub-Api-Version: 2022-11-28", endpoint]
    if paginated:
        arguments.append("--paginate")
    result = _pages(_run(arguments, deadline, "GitHub source read"), paginated)
    _remaining(deadline)
    return result


def _field(value: Any, key: str, expected: type, *, nullable: bool = False) -> Any:
    if not isinstance(value, dict) or key not in value:
        raise Refusal("GitHub source is missing a required field.")
    item = value[key]
    if nullable and item is None:
        return None
    if type(item) is not expected:
        raise Refusal("GitHub source contains an invalid field type.")
    return item


def _nonempty(value: Any, key: str) -> str:
    item = _field(value, key, str)
    if not item.strip() or "\x00" in item:
        raise Refusal("GitHub source contains an empty identity field.")
    return item


def _native_id(value: Any) -> tuple[int, str]:
    database_id = _field(value, "id", int)
    if database_id <= 0:
        raise Refusal("GitHub source contains an invalid native identity.")
    return database_id, _nonempty(value, "node_id")


def _repository(value: Any, expected_name: str | None = None) -> dict:
    _, native_id = _native_id(value)
    name = repository_name(_nonempty(value, "full_name"))
    if expected_name is not None and name != expected_name:
        raise Refusal("GitHub returned a different repository.")
    return {"name": name, "id": native_id}


def _timestamp(value: Any, key: str, *, nullable: bool = False) -> str | None:
    item = _field(value, key, str, nullable=nullable)
    if item is not None:
        try:
            parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except ValueError:
            raise Refusal("GitHub source contains an invalid timestamp.") from None
    return item


def _body(value: Any, number: int, repository_id: str, kind: str) -> dict:
    _, native_id = _native_id(value)
    if _field(value, "number", int) != number:
        raise Refusal("GitHub returned a different object number.")
    state = _field(value, "state", str)
    if state not in {"open", "closed"}:
        raise Refusal("GitHub returned an unknown lifecycle state.")
    content = {"kind": kind, "repository_id": repository_id, "id": native_id, "number": number,
               "title": _field(value, "title", str), "body": _field(value, "body", str, nullable=True)}
    return {"number": number, "id": native_id, "state": state, "content_sha256": content_digest(content)}


def _discussion(rows: list, name: str) -> list[dict]:
    result = []
    for row in rows:
        _, native_id = _native_id(row)
        author = _field(row, "user", dict, nullable=True)
        if author is not None:
            database_id, user_id = _native_id(author)
            author = {"id": database_id, "node_id": user_id, "login": _nonempty(author, "login")}
        content = {"id": native_id, "body": _field(row, "body", str, nullable=True), "author": author}
        if name == "pull_request_reviews":
            submitted = _timestamp(row, "submitted_at", nullable=True)
            updated = None
            content.update(state=_nonempty(row, "state"), submitted_at=submitted,
                           commit_id=_field(row, "commit_id", str, nullable=True))
        else:
            updated = _timestamp(row, "updated_at")
            submitted = None
            content.update(created_at=_timestamp(row, "created_at"), updated_at=updated)
        if name == "pull_request_review_comments":
            content.update(pull_request_review_id=_field(row, "pull_request_review_id", int),
                           path=_field(row, "path", str), diff_hunk=_field(row, "diff_hunk", str),
                           commit_id=_field(row, "commit_id", str),
                           original_commit_id=_field(row, "original_commit_id", str))
            for key in ("in_reply_to_id", "line", "original_line", "start_line", "original_start_line", "position", "original_position"):
                if key in row:
                    content[key] = _field(row, key, int, nullable=True)
            for key in ("side", "start_side", "original_start_side", "subject_type"):
                if key in row:
                    content[key] = _field(row, key, str, nullable=True)
        result.append({"id": native_id, "updated_at": updated, "submitted_at": submitted,
                       "content_sha256": content_digest(content)})
    return sorted(result, key=lambda row: row["id"])


def _observe_once(repository: str, issue_number: int, pull_number: int, deadline: float) -> dict:
    prefix = "repos/" + repository
    endpoints = {
        "repository": (prefix, False),
        "issue": (f"{prefix}/issues/{issue_number}", False),
        "proposal": (f"{prefix}/pulls/{pull_number}", False),
        "issue_comments": (f"{prefix}/issues/{issue_number}/comments?per_page=100", True),
        "pull_request_issue_comments": (f"{prefix}/issues/{pull_number}/comments?per_page=100", True),
        "pull_request_reviews": (f"{prefix}/pulls/{pull_number}/reviews?per_page=100", True),
        "pull_request_review_comments": (f"{prefix}/pulls/{pull_number}/comments?per_page=100", True),
    }
    _remaining(deadline)
    with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
        futures = {name: pool.submit(_read, endpoint, paginated, deadline)
                   for name, (endpoint, paginated) in endpoints.items()}
        data = {name: future.result() for name, future in futures.items()}
    _remaining(deadline)
    repo = _repository(data["repository"], repository)
    issue = data["issue"]
    if "pull_request" in issue:
        raise Refusal("The requirement reference resolves to a pull request.")
    if _nonempty(issue, "repository_url").casefold() != "https://api.github.com/repos/" + repository:
        raise Refusal("Requirement repository identity is inconsistent.")
    proposal = _body(data["proposal"], pull_number, repo["id"], "proposal")
    proposal["draft"] = _field(data["proposal"], "draft", bool)
    for side in ("head", "base"):
        branch = _field(data["proposal"], side, dict)
        branch_repo = _repository(_field(branch, "repo", dict))
        proposal[side + "_repository_id"] = branch_repo["id"]
        proposal[side + "_ref"] = _nonempty(branch, "ref")
        # A branch commit is observed for schema completeness, but is not design content.
        _nonempty(branch, "sha")
    if proposal["base_repository_id"] != repo["id"]:
        raise Refusal("Proposal base belongs to a different repository.")
    basis = {"complete": True, "repository": repo,
             "issue": _body(issue, issue_number, repo["id"], "requirement"), "proposal": proposal,
             "discussions": {name: _discussion(data[name], name) for name in DISCUSSIONS}}
    return parse_basis(basis).to_dict()


def observe_basis(repository: str, issue_number: int, pull_number: int, deadline: float) -> dict:
    """Return one complete serializable basis after two equal complete passes."""
    repository = repository_name(repository)
    if any(type(number) is not int or number <= 0 for number in (issue_number, pull_number)):
        raise Refusal("Native Issue and PR numbers must be positive integers.")
    first = _observe_once(repository, issue_number, pull_number, deadline)
    second = _observe_once(repository, issue_number, pull_number, deadline)
    _remaining(deadline)
    if first != second:
        raise Refusal("GitHub sources changed during observation; reassess the assignment.")
    return second


def _remote_repository(url: str) -> str:
    if url.startswith("git@github.com:"):
        path = url.removeprefix("git@github.com:")
    else:
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"https", "ssh"} or parsed.hostname != "github.com" or parsed.query or parsed.fragment:
                raise ValueError
            if parsed.port not in (None, 443 if parsed.scheme == "https" else 22):
                raise ValueError
            path = parsed.path.removeprefix("/")
        except ValueError:
            raise Refusal("The declared remote is not a supported GitHub remote.") from None
    return repository_name(path.removesuffix(".git"))


def check_checkout(context: Context, cwd: Path, deadline: float) -> None:
    """Bind a record to the actual checkout, declared remote and native repo."""
    try:
        observed_cwd = Path(cwd)
        if not observed_cwd.is_absolute():
            raise Refusal("The observed working directory must be absolute.")
        observed_cwd = observed_cwd.resolve(strict=True)
        root = context.root.resolve(strict=True)
        if context.root != root or not root.is_dir() or not observed_cwd.is_relative_to(root):
            raise Refusal("The observed checkout differs from the assignment.")
        prefix = ["git", "-C", str(observed_cwd)]
        actual_root = Path(_run(prefix + ["rev-parse", "--show-toplevel"], deadline, "Checkout read").strip()).resolve(strict=True)
        if actual_root != root:
            raise Refusal("The actual Git root differs from the assignment.")
        remote_lines = _run(prefix + ["remote", "get-url", "--all", "--", context.repository.remote], deadline, "Git remote read").splitlines()
        if not remote_lines or any(_remote_repository(url) != context.repository.name for url in remote_lines):
            raise Refusal("The actual Git remote differs from the assignment.")
        observed = _repository(_read("repos/" + context.repository.name, False, deadline), context.repository.name)
        if observed["id"] != context.repository.id:
            raise Refusal("The native repository identity differs from the assignment.")
    except (OSError, ValueError, TypeError):
        raise Refusal("The checkout boundary could not be resolved.") from None


def check_source_basis(context: Context, deadline: float) -> None:
    """Preparation adds no implementation prerequisites after checkout checking."""
    _remaining(deadline)
    if context.kind == "preparation":
        return
    implementation = context.implementation
    if implementation is None:
        raise Refusal("Implementation evidence is missing.")
    current = observe_basis(context.repository.name, implementation.issue_number, implementation.pull_number, deadline)
    if parse_basis(current) != implementation.basis:
        raise Refusal("The current native basis differs from the admitted basis; reassessment is required.")

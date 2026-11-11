"""Resolve explicit private installation metadata without granting authority."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tomllib
from typing import Any

from .contracts import Context, Refusal
from .sources import _remaining, _run, load_context


CONTEXT_VARIABLE = "GRAPHVON_CONTEXT"


@dataclass(frozen=True)
class Installation:
    context_path: Path
    context: Context
    working_record: Path | None

    @property
    def skill_path(self) -> Path:
        return self.context.root / ".agents/skills/graphvon-start-work/SKILL.md"


def _absolute_path(value: Any) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise Refusal("Expected an absolute installation path.")
    path = Path(value)
    if not path.is_absolute():
        raise Refusal("Expected an absolute installation path.")
    return path


def _configuration() -> dict[str, tuple[Path, Path]]:
    """Read one TOML file; a FIFO or other non-regular input must not block."""
    try:
        base = os.environ.get("XDG_CONFIG_HOME")
        directory = _absolute_path(base) if base else Path.home() / ".config"
        descriptor = os.open(directory / "graphvon/config.toml", os.O_RDONLY | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise Refusal("Installation configuration must be a regular file.")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                value = tomllib.load(stream)
        finally:
            os.close(descriptor)
        if set(value) != {"version", "projects"} or type(value["version"]) is not int or value["version"] != 1:
            raise Refusal("Unsupported installation configuration.")
        projects = value["projects"]
        if not isinstance(projects, dict):
            raise Refusal("Expected checkout registrations.")
        result = {}
        for key, entry in projects.items():
            root = _absolute_path(key)
            if str(root) != key or ".." in root.parts:
                raise Refusal("Registration keys must be canonical checkout roots.")
            if not isinstance(entry, dict) or set(entry) != {"context", "working_record"}:
                raise Refusal("Invalid checkout registration.")
            result[key] = (_absolute_path(entry["context"]), _absolute_path(entry["working_record"]))
        return result
    except (OSError, ValueError, TypeError, RecursionError):
        raise Refusal("Installation configuration could not be read or validated.") from None


def resolve_installation(cwd: Path, deadline: float) -> Installation:
    """Bind the effective cwd's Git worktree to an override or exact registration.

    Explicit overrides are self-contained and never consult registration, even
    when invalid. They therefore supply no registered working-record locator.
    Local root validation precedes any returned private references. The existing
    pre-tool checks still validate the remote, native identity and source basis.
    """
    try:
        observed_cwd = _absolute_path(str(cwd)).resolve(strict=True)
        output = _run(["git", "-C", str(observed_cwd), "rev-parse", "--show-toplevel"],
                      deadline, "Checkout read")
        root = _absolute_path(output.removesuffix("\n")).resolve(strict=True)
        if not root.is_dir() or not observed_cwd.is_relative_to(root):
            raise Refusal("The effective checkout could not be confirmed.")
        if CONTEXT_VARIABLE in os.environ:
            locator = _absolute_path(os.environ[CONTEXT_VARIABLE])
            working_record = None
        else:
            entry = _configuration().get(str(root))
            if entry is None:
                raise Refusal("The effective checkout has no registration.")
            locator, working_record = entry
        context = load_context(locator)
        if context.root != root:
            raise Refusal("The context belongs to a different checkout.")
        _remaining(deadline)
        return Installation(locator, context, working_record)
    except (OSError, ValueError, TypeError, RuntimeError):
        raise Refusal("The installation binding could not be resolved.") from None

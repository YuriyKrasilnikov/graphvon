"""Inspect native patch effects without applying them.

The supported profile is a local POSIX checkout with no concurrent filesystem
mutation. Inspection does not prove that update text matches the source or that
the native writer will succeed. Native application can fail after partial writes.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Literal

from .contracts import Grant, Refusal


@dataclass(frozen=True)
class Effect:
    """One attempted effect, using an exact repository-relative POSIX path."""

    operation: str
    path: str
    replace_existing: bool = False


@dataclass(frozen=True)
class _Line:
    kind: Literal["context", "add", "remove"]
    text: str


@dataclass(frozen=True)
class _Chunk:
    context: str | None
    lines: tuple[_Line, ...]
    at_end: bool


@dataclass(frozen=True)
class _Add:
    path: str
    contents: str


@dataclass(frozen=True)
class _Delete:
    path: str


@dataclass(frozen=True)
class _Update:
    path: str
    move_to: str | None
    chunks: tuple[_Chunk, ...]


_Operation = _Add | _Delete | _Update
_BEGIN = "*** Begin Patch"
_END = "*** End Patch"
_EOF = "*** End of File"
_MOVE = "*** Move to: "
_HEADERS = {
    "*** Add File: ": "add",
    "*** Delete File: ": "delete",
    "*** Update File: ": "update",
}
# Rust str::trim uses Unicode White_Space. Python also strips four additional
# control characters, so its default strip would accept different headers.
_SPACE = "\t\n\v\f\r \u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
_KINDS = {" ": "context", "+": "add", "-": "remove"}


def _header(line: str) -> tuple[str, str] | None:
    for prefix, operation in _HEADERS.items():
        if line.startswith(prefix):
            return operation, line[len(prefix):]
    return None


def _update(lines: list[str], index: int, path: str) -> tuple[_Update, int]:
    move_to = None
    chunks: list[_Chunk] = []
    context = None
    content: list[_Line] = []
    started = False
    at_end = False
    while index < len(lines) - 1:
        line = lines[index]
        marker = line.rstrip(_SPACE)
        # Inside an update, leading spaces are context, including lines that
        # resemble file headers. The native parser trims only the right side.
        if _header(marker) is not None or marker == _END:
            break
        if at_end:
            if not marker:
                index += 1
                continue
            if marker != "@@" and not marker.startswith("@@ "):
                raise Refusal("An end-of-file marker must end an update chunk.")
        if not started and move_to is None and marker.startswith(_MOVE):
            move_to = marker[len(_MOVE):]
        elif marker == "@@" or marker.startswith("@@ "):
            if started:
                if not content:
                    raise Refusal("An update chunk must contain patch lines.")
                chunks.append(_Chunk(context, tuple(content), at_end))
            context = None if marker == "@@" else marker[3:]
            content = []
            started = True
            at_end = False
        elif marker == _EOF:
            if started:
                if not content:
                    raise Refusal("An update chunk must contain patch lines.")
                at_end = True
        elif not line or line[0] in _KINDS:
            started = True
            if line:
                content.append(_Line(_KINDS[line[0]], line[1:]))
            else:
                content.append(_Line("context", ""))
        else:
            raise Refusal("An update contains an unsupported or malformed line.")
        index += 1
    if not started or not content:
        raise Refusal("An update must contain a nonempty patch chunk.")
    chunks.append(_Chunk(context, tuple(content), at_end))
    return _Update(path, move_to, tuple(chunks)), index


def _parse(command: str) -> tuple[_Operation, ...]:
    if not isinstance(command, str):
        raise Refusal("The patch command must be text.")
    try:
        command.encode("utf-8")
    except UnicodeError:
        raise Refusal("The patch command must be valid UTF-8 text.") from None
    # str.splitlines also splits Unicode line separators that the native
    # parser treats as content. Split only LF, with native CRLF handling.
    lines = [line.removesuffix("\r") for line in command.strip(_SPACE).split("\n")]
    if lines and lines[0] in {"<<EOF", "<<'EOF'", '<<"EOF"'}:
        if len(lines) < 4 or lines[-1] != "EOF":
            raise Refusal("The patch heredoc wrapper is malformed.")
        lines = lines[1:-1]
    if (
        len(lines) < 2
        or lines[0].strip(_SPACE) != _BEGIN
        or lines[-1].strip(_SPACE) != _END
    ):
        raise Refusal("The patch must have complete native patch boundaries.")
    operations: list[_Operation] = []
    index = 1
    while index < len(lines) - 1:
        marker = lines[index].strip(_SPACE)
        if marker.startswith("*** Environment ID:"):
            raise Refusal("Environment-directed patches are outside the local profile.")
        header = _header(marker)
        if header is None:
            raise Refusal("The patch contains an unsupported or malformed file header.")
        operation, path = header
        index += 1
        if operation == "delete":
            operations.append(_Delete(path))
        elif operation == "update":
            update, index = _update(lines, index, path)
            operations.append(update)
        else:
            added: list[str] = []
            while index < len(lines) - 1:
                line = lines[index]
                marker = line.strip(_SPACE)
                if _header(marker) is not None or marker == _END:
                    break
                if not line.startswith("+"):
                    raise Refusal("An addition contains an unsupported or malformed line.")
                added.append(line[1:] + "\n")
                index += 1
            operations.append(_Add(path, "".join(added)))
    if not operations:
        raise Refusal("The patch does not contain file operations.")
    return tuple(operations)


def _directory(path: Path) -> None:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.anchor != "/"
        or ".." in path.parts
    ):
        raise Refusal("The checkout root and working directory must be absolute POSIX directories.")
    current = Path("/")
    for component in path.parts[1:]:
        current /= component
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise Refusal("The checkout root and working directory must contain only real directories.")


def _resolve(path: str, cwd: Path, root: Path) -> Path:
    if not path or "\0" in path or path.startswith("//") or path.endswith("/"):
        raise Refusal("A patch path is empty, ambiguous or unsupported.")
    resolved = Path(os.path.normpath(cwd / path))
    if resolved == root or not resolved.is_relative_to(root):
        raise Refusal("A patch path escapes the checkout boundary or names its root.")
    return resolved


def _observe(path: Path, root: Path) -> tuple[bool, tuple[Path, ...]]:
    """Return existence and missing parents, without following any links."""
    current = root
    missing: list[Path] = []
    parts = path.relative_to(root).parts
    for index, component in enumerate(parts):
        current /= component
        is_file = index == len(parts) - 1
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if not is_file:
                missing.append(current)
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise Refusal("Symlink components are outside the supported patch profile.")
        if is_file:
            if not stat.S_ISREG(metadata.st_mode):
                raise Refusal("A patch endpoint must be a regular file or absent.")
            if metadata.st_nlink != 1:
                raise Refusal("Multiply-linked files are outside the supported patch profile.")
            return True, tuple(missing)
        if not stat.S_ISDIR(metadata.st_mode):
            raise Refusal("A patch parent must be a real directory or absent.")
    return False, tuple(missing)


def _grants(grants: tuple[Grant, ...]) -> dict[tuple[str, str], Grant]:
    if not isinstance(grants, tuple):
        raise Refusal("Patch grants must be an immutable tuple.")
    result: dict[tuple[str, str], Grant] = {}
    for grant in grants:
        if not isinstance(grant, Grant):
            raise Refusal("Each patch grant must use the validated Grant contract.")
        key = grant.operation, grant.path
        if key in result:
            raise Refusal("Patch grants must not repeat an operation and path.")
        result[key] = grant
    return result


def inspect_patch(
    command: str, cwd: Path, root: Path, grants: tuple[Grant, ...]
) -> tuple[Effect, ...]:
    """Validate the complete attempted effect set, or raise ``Refusal``.

    Plain native patches and exact EOF heredoc wrappers are supported; no shell
    text is evaluated. Environment IDs and repeated or overlapping file
    endpoints are unsupported. A move needs move_from and move_to grants;
    every newly-created parent needs its own mkdir grant. Additions and move
    destinations that already exist require explicit replacement admission.
    """
    if os.name != "posix":
        raise Refusal("Only the local POSIX patch profile is supported.")
    operations = _parse(command)
    admitted = _grants(grants)
    try:
        _directory(root)
        _directory(cwd)
        if not cwd.is_relative_to(root):
            raise Refusal("The working directory is outside the checkout boundary.")
        endpoints: list[tuple[str, Path]] = []
        for operation in operations:
            path = _resolve(operation.path, cwd, root)
            if isinstance(operation, _Add):
                endpoints.append(("add", path))
            elif isinstance(operation, _Delete):
                endpoints.append(("delete", path))
            elif operation.move_to is None:
                endpoints.append(("update", path))
            else:
                endpoints.append(("move_from", path))
                endpoints.append(("move_to", _resolve(operation.move_to, cwd, root)))
        paths = {path for _, path in endpoints}
        if len(paths) != len(endpoints) or any(
            parent in paths for path in paths for parent in path.parents
        ):
            raise Refusal("Sequential edits to repeated or overlapping endpoints are unsupported.")
        effects: list[Effect] = []
        created_parents: set[Path] = set()
        for operation, path in endpoints:
            exists, missing_parents = _observe(path, root)
            if operation in {"update", "delete", "move_from"} and not exists:
                raise Refusal("An update, deletion or move source must already exist.")
            for parent in missing_parents:
                if parent not in created_parents:
                    effects.append(Effect("mkdir", parent.relative_to(root).as_posix()))
                    created_parents.add(parent)
            effects.append(Effect(
                operation,
                path.relative_to(root).as_posix(),
                exists and operation in {"add", "move_to"},
            ))
    except (OSError, ValueError, UnicodeError):
        raise Refusal("The patch filesystem paths could not be inspected safely.") from None
    for effect in effects:
        grant = admitted.get((effect.operation, effect.path))
        if grant is None:
            raise Refusal("A patch effect is outside the exact assignment grants.")
        if effect.replace_existing and not grant.replace_existing:
            raise Refusal("Replacing existing content requires an explicit replacement grant.")
    return tuple(effects)

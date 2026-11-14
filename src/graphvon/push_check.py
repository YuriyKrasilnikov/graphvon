"""Read-only exact-literal inspection for a bounded Git pre-push profile."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from .contracts import Refusal, parse_json
from .issue_contracts import obj, text


class Found(Exception):
    def __init__(self, identity, category):
        self.identity = identity
        self.category = category


class InvalidInput(Refusal):
    pass


class Unsupported(Refusal):
    pass


def read_ordinary(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode): raise Refusal("Not an ordinary file.")
            with os.fdopen(fd, "rb", closefd=False) as stream: return stream.read()
        finally: os.close(fd)
    except OSError: raise Refusal("Private input unavailable.") from None


def _parse_policy(data: bytes, root: Path) -> dict:
    try: policy = parse_json(data.decode("utf-8"))
    except (UnicodeError, ValueError): raise Refusal("Invalid private policy.") from None
    obj(policy, {"version", "checkout", "destinations", "owner", "authority", "protected_literals"})
    if type(policy["version"]) is not int or policy["version"] != 1 or policy["destinations"] != "all": raise Refusal("Unsupported policy.")
    if text(policy["checkout"]) != str(root): raise Refusal("Policy checkout mismatch.")
    text(policy["owner"])
    def sources(rows):
        if not isinstance(rows, list) or not rows: raise Refusal("Policy source references required.")
        for row in rows:
            obj(row, {"locator", "description"}); text(row["locator"]); text(row["description"])
    sources(policy["authority"])
    if not isinstance(policy["protected_literals"], list): raise Refusal("Invalid policy literals.")
    ids = set()
    for row in policy["protected_literals"]:
        obj(row, {"id", "value", "owner", "sources", "applicability", "retirement_condition"})
        for name in ("id", "owner", "applicability", "retirement_condition"): text(row[name])
        if not isinstance(row["value"], str) or not row["value"]: raise InvalidInput("Empty policy literal.")
        row["value"].encode("utf-8")
        sources(row["sources"])
        if row["id"] in ids: raise Refusal("Duplicate policy entry.")
        ids.add(row["id"])
    return policy


def policy_from_bytes(data: bytes, root: Path) -> dict:
    try: return _parse_policy(data, root)
    except (Refusal, UnicodeError, TypeError, ValueError): raise InvalidInput("Invalid private policy.") from None


def git_env() -> dict:
    for key in ("GIT_SHALLOW_FILE", "GIT_REPLACE_REF_BASE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_GRAFT_FILE", "GIT_NAMESPACE"):
        if os.environ.get(key): raise Unsupported("Unsupported Git environment.")
    return {**os.environ, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0"}


def git(root: Path, *arguments: str, allow_missing: bool = False) -> bytes:
    try:
        run = subprocess.run(["git", "-C", str(root), *arguments], capture_output=True, env=git_env(), check=False)
    except OSError: raise Refusal("Git unavailable.") from None
    if run.returncode and not (allow_missing and run.returncode == 1): raise Refusal("Git observation unavailable.")
    return run.stdout


def identity(root: Path) -> tuple[Path, Path, Path]:
    try:
        root = root.resolve(strict=True)
        actual = Path(os.fsdecode(git(root, "rev-parse", "--show-toplevel").strip())).resolve(strict=True)
        gitdir = Path(os.fsdecode(git(root, "rev-parse", "--absolute-git-dir").strip())).resolve(strict=True)
        common_raw = os.fsdecode(git(root, "rev-parse", "--git-common-dir").strip())
        common = (root / common_raw).resolve(strict=True)
        if actual != root or git(root, "rev-parse", "--is-bare-repository").strip() != b"false": raise Unsupported("Unsupported checkout.")
        return root, gitdir, common
    except (OSError, ValueError, UnicodeError): raise Refusal("Checkout identity unavailable.") from None


def profile(root: Path, gitdir: Path, common: Path) -> int:
    if git(root, "rev-parse", "--is-shallow-repository").strip() != b"false": raise Unsupported("Shallow repository unsupported.")
    kind = git(root, "rev-parse", "--show-object-format").strip()
    width = {b"sha1": 40, b"sha256": 64}.get(kind)
    if width is None: raise Unsupported("Unsupported object format.")
    configured = git(root, "config", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor|remote\..*\.partialclonefilter)$", allow_missing=True)
    replacements = git(root, "for-each-ref", "--format=%(refname)", "refs/replace/")
    if configured.strip() or replacements.strip(): raise Unsupported("Unsupported object substitution or partial clone.")
    for path in (common / "objects", common / "objects/pack", common / "objects/info"):
        if path.is_symlink(): raise Unsupported("Linked object store unsupported.")
    for path in (gitdir / "info/grafts", common / "info/grafts", common / "objects/info/alternates", common / "shallow"):
        if path.exists() or path.is_symlink(): raise Unsupported("Unsupported object store configuration.")
    if any((common / "objects/pack").glob("*.promisor")): raise Unsupported("Promisor packs unsupported.")
    return width


def updates_from_bytes(data: bytes, width: int) -> list[tuple[bytes, bytes, bytes, bytes]]:
    if data and not data.endswith(b"\n"): raise InvalidInput("Incomplete pre-push protocol.")
    result = []; destinations = {}; zero = b"0" * width
    for line in data.splitlines():
        fields = line.split(b" ")
        if len(fields) != 4 or any(not f for f in fields): raise InvalidInput("Invalid pre-push protocol.")
        local, new, remote, old = fields
        if not all(re.fullmatch(rb"[0-9a-f]{" + str(width).encode() + rb"}", oid) for oid in (new, old)): raise InvalidInput("Invalid object identifier.")
        record = (local, new, remote, old)
        if remote in destinations:
            if destinations[remote] != record: raise InvalidInput("Contradictory destination updates.")
            continue
        destinations[remote] = record
        if not (remote.startswith(b"refs/heads/") or remote.startswith(b"refs/tags/")): raise Unsupported("Unsupported destination namespace.")
        if git_ref_invalid(remote): raise InvalidInput("Invalid destination ref.")
        if (new == zero) != (local == b"(delete)"): raise InvalidInput("Invalid deletion record.")
        result.append((local, new, remote, old))
    return result


def git_ref_invalid(ref: bytes) -> bool:
    return (not ref.startswith(b"refs/") or ref.endswith((b"/", b".", b".lock")) or b".." in ref or b"@{" in ref
            or b"//" in ref or any(c < 32 or c == 127 or c in b" ~^:?*[\\" for c in ref)
            or any(not part or part.startswith(b".") or part.endswith(b".lock") for part in ref.split(b"/")))


class Objects:
    def __init__(self, root: Path, width: int, literals: list[tuple[str, bytes]]):
        self.width = width; self.literals = literals; self.cache = {}; self.kinds = {}
        try:
            self.proc = subprocess.Popen(["git", "-C", str(root), "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=git_env())
        except OSError: raise Refusal("Object reader unavailable.") from None

    def close(self):
        self.proc.stdin.close(); self.proc.stdout.close(); self.proc.terminate(); self.proc.wait()

    def match(self, data: bytes, category: str):
        for identity, value in self.literals:
            if value in data: raise Found(identity, category)

    def read(self, oid: bytes, *, scan: bool) -> tuple[bytes, bytes | None]:
        if not re.fullmatch(rb"[0-9a-f]{" + str(self.width).encode() + rb"}", oid):
            raise Refusal("Invalid referenced object identifier.")
        if oid in self.cache:
            kind, value = self.cache[oid]
            if scan and value is not None and kind != b"tree": self.match(value, kind.decode())
            return kind, value
        try:
            self.proc.stdin.write(oid + b"\n"); self.proc.stdin.flush()
            header = self.proc.stdout.readline().rstrip(b"\n").split(b" ")
            if len(header) != 3 or header[0] != oid or header[1] not in {b"commit", b"tree", b"blob", b"tag"} or not header[2].isdigit(): raise Refusal("Object unavailable or invalid.")
            kind, size = header[1], int(header[2]); remaining = size; parts = []
            self.kinds[oid] = kind
            overlap = b""; tail = max((len(v) for _, v in self.literals), default=1) - 1
            while remaining:
                chunk = self.proc.stdout.read(min(65536, remaining))
                if not chunk: raise Refusal("Incomplete object.")
                remaining -= len(chunk)
                if scan and kind != b"tree": self.match(overlap + chunk, kind.decode())
                if kind != b"blob": parts.append(chunk)
                overlap = (overlap + chunk)[-tail:] if tail else b""
            if self.proc.stdout.read(1) != b"\n": raise Refusal("Invalid object framing.")
            value = b"".join(parts) if kind != b"blob" else None
            if kind != b"blob": self.cache[oid] = (kind, value)
            return kind, value
        except (OSError, BrokenPipeError): raise Refusal("Object reader failed.") from None


def _entries(data: bytes, width: int):
    pos = 0; size = width // 2
    while pos < len(data):
        space = data.find(b" ", pos); nul = data.find(b"\0", space + 1)
        if space < 0 or nul < 0 or nul + 1 + size > len(data): raise Refusal("Invalid tree framing.")
        mode, name = data[pos:space], data[space+1:nul]
        if mode not in {b"40000", b"100644", b"100755", b"120000", b"160000"} or not name or b"/" in name or name in {b".", b".."}: raise Refusal("Unsupported tree entry.")
        yield mode, name, data[nul+1:nul+1+size].hex().encode()
        pos = nul + 1 + size


def _walk(objects: Objects, roots: list[bytes], excluded: set[bytes], inspect: bool) -> set[bytes]:
    seen = set(); blobs_scanned = set(); active = set()
    stack = [("visit", root, None, b"") for root in reversed(roots)]
    while stack:
        task, oid, expected, path = stack.pop()
        if task == "leave":
            active.remove(oid)
            continue
        if oid in active: raise Refusal("Cyclic object graph.")
        if oid in seen and expected != b"tree":
            if expected is not None and objects.kinds[oid] != expected: raise Refusal("Unexpected object type.")
            continue
        active.add(oid); seen.add(oid)
        scan = inspect and oid not in excluded
        kind, data = objects.read(oid, scan=scan and oid not in blobs_scanned)
        if expected is not None and kind != expected: raise Refusal("Unexpected object type.")
        if inspect and oid in excluded and kind in {b"commit", b"tag"}:
            active.remove(oid)
            continue
        stack.append(("leave", oid, None, b""))
        if kind == b"blob": blobs_scanned.add(oid)
        elif kind == b"tree":
            for mode, name, child in _entries(data, objects.width):
                full = path + (b"/" if path else b"") + name
                if inspect: objects.match(full, "path")
                if mode == b"160000":
                    if inspect: objects.match(child, "gitlink")
                    continue
                stack.append(("visit", child, b"tree" if mode == b"40000" else b"blob", full))
        elif kind == b"commit":
            headers = data.split(b"\n\n", 1)[0].splitlines(); trees = [x[5:] for x in headers if x.startswith(b"tree ")]
            parents = [x[7:] for x in headers if x.startswith(b"parent ")]
            if len(trees) != 1: raise Refusal("Invalid commit.")
            stack.append(("visit", trees[0], b"tree", b""))
            for parent in parents: stack.append(("visit", parent, b"commit", b""))
        else:
            lines = data.split(b"\n\n", 1)[0].splitlines(); targets = [x[7:] for x in lines if x.startswith(b"object ")]; types = [x[5:] for x in lines if x.startswith(b"type ")]
            if len(targets) != 1 or len(types) != 1 or types[0] not in {b"tag", b"commit"}: raise Refusal("Unsupported tag target.")
            stack.append(("visit", targets[0], types[0], b""))
    return seen


def check_push(root: Path, policy: dict, stream: bytes) -> dict:
    root, gitdir, common = identity(root); width = profile(root, gitdir, common)
    policy_from_bytes(json.dumps(policy, ensure_ascii=False).encode(), root)
    updates = updates_from_bytes(stream, width); zero = b"0" * width
    literals = [(row["id"], row["value"].encode("utf-8")) for row in policy["protected_literals"]]
    objects = Objects(root, width, literals)
    try:
        roots = []
        for _, new, remote, _ in updates:
            if new == zero: continue
            objects.match(remote, "destination_ref")
            kind, _ = objects.read(new, scan=False)
            if remote.startswith(b"refs/heads/") and kind != b"commit": raise Refusal("Branch target is not a commit.")
            if remote.startswith(b"refs/tags/") and kind not in {b"commit", b"tag"}: raise Refusal("Unsupported tag target.")
            roots.append(new)
        old = set()
        if roots:
            for _, _, remote, prior in updates:
                if prior != zero:
                    try:
                        kind, _ = objects.read(prior, scan=False)
                        if remote.startswith(b"refs/heads/") and kind != b"commit": continue
                        if remote.startswith(b"refs/tags/") and kind not in {b"commit", b"tag"}: continue
                        old.update(_walk(objects, [prior], set(), False))
                    except Refusal: pass
        _walk(objects, roots, old, True)
        return {"status": "checked", "invocation": "standalone", "installation_verified": False}
    except Found as found:
        return {"status": "literal_found", "category": found.category,
                "invocation": "standalone", "installation_verified": False}
    finally: objects.close()


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise InvalidInput("Invalid command input.")


def main(argv=None) -> int:
    parser = SafeParser(description="Inspect a supported Git push for declared private literals.")
    sub = parser.add_subparsers(dest="operation", required=True)
    check = sub.add_parser("check"); check.add_argument("--policy", required=True); check.add_argument("--remote-name", required=True); check.add_argument("--remote-location", required=True)
    sub.add_parser("install"); sub.add_parser("uninstall")
    operation = "unknown"
    try:
        args = parser.parse_args(argv)
        operation = args.operation
        if args.operation == "check":
            path = Path(args.policy)
            if not path.is_absolute(): raise InvalidInput("Policy path must be absolute.")
            root, _, _ = identity(Path.cwd()); policy = policy_from_bytes(read_ordinary(path), root)
            result = check_push(root, policy, sys.stdin.buffer.read())
        else:
            from .push_installation import lifecycle
            try: request = parse_json(sys.stdin.read())
            except Refusal: raise InvalidInput("Invalid lifecycle request.") from None
            result = lifecycle(args.operation, request)
        print(json.dumps(result, ensure_ascii=False))
        if result["status"] == "literal_found": return 1
        return 0 if result["status"] in {"checked", "not_adopted", "active", "removed"} else 2
    except InvalidInput:
        print(json.dumps({"status": "invalid_input", "operation": operation}))
        return 2
    except Unsupported:
        print(json.dumps({"status": "unsupported", "operation": operation}))
        return 2
    except (Refusal, OSError, ValueError, TypeError, RecursionError):
        print(json.dumps({"status": "unavailable", "operation": operation}))
        return 2


if __name__ == "__main__": raise SystemExit(main())

"""Owned local pre-push launcher and explicit interruption recovery."""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
import shlex
import stat
import sys
import tempfile
import uuid

from .contracts import Refusal, parse_json
from .issue_contracts import obj, text
from .push_check import InvalidInput, Unsupported, check_push, git, identity, policy_from_bytes, profile, read_ordinary


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def launcher(binding: dict) -> bytes:
    args = [sys.executable, "-m", "graphvon.push_installation", "--installed", binding["installation_id"],
            binding["checkout"], binding["git_directory"], binding["common_directory"],
            binding["binding_path"], binding["launcher_path"]]
    return ("#!/bin/sh\nexec " + " ".join(shlex.quote(x) for x in args) + ' "$@"\n').encode()


def _path(value) -> Path:
    try: path = Path(text(value))
    except (Refusal, TypeError, ValueError): raise InvalidInput("Explicit absolute path required.") from None
    if not path.is_absolute(): raise InvalidInput("Explicit absolute path required.")
    return path


def _absent(path: Path) -> bool:
    return not path.exists() and not path.is_symlink()


def _save(path: Path, value: dict, *, create: bool = False, expected: dict | None = None) -> None:
    temporary = None
    try:
        if create and not _absent(path): raise Refusal("Binding already exists.")
        if not create and (expected is None or _load(path) != expected): raise Refusal("Binding ownership changed.")
        fd, temporary = tempfile.mkstemp(prefix=".push-binding-", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
            stream.flush(); os.fsync(stream.fileno())
        if create:
            os.link(temporary, path, follow_symlinks=False); os.unlink(temporary)
        else:
            if _load(path) != expected: raise Refusal("Binding ownership changed.")
            os.replace(temporary, path)
        temporary = None
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    except OSError: raise Refusal("Binding persistence unavailable.") from None
    finally:
        if temporary is not None:
            try: os.unlink(temporary)
            except OSError: pass


def _load(path: Path) -> dict:
    try: value = parse_json(read_ordinary(path).decode("utf-8"))
    except UnicodeError: raise Refusal("Invalid binding.") from None
    obj(value, {"version", "installation_id", "checkout", "git_directory", "common_directory", "policy_path", "policy_sha256", "launcher_path", "launcher_sha256", "binding_path", "lifecycle"})
    if type(value["version"]) is not int or value["version"] != 1 or value["lifecycle"] not in {"installing", "active", "removing"}: raise Refusal("Invalid binding.")
    for key in value:
        if key != "version": text(value[key])
    return value


def _owned(binding: dict, root: Path, gitdir: Path, common: Path, binding_path: Path, hook: Path, expected: str) -> None:
    expected_values = {"installation_id": expected, "checkout": str(root), "git_directory": str(gitdir), "common_directory": str(common),
                       "binding_path": str(binding_path), "launcher_path": str(hook)}
    if any(binding[key] != value for key, value in expected_values.items()): raise Refusal("Installation identity differs.")
    generated = launcher(binding)
    if sha(generated) != binding["launcher_sha256"]: raise Refusal("Launcher identity differs.")
    if not _absent(hook):
        if read_ordinary(hook) != generated or not (os.lstat(hook).st_mode & 0o111): raise Refusal("Foreign or modified hook.")


def _install_hook(hook: Path, data: bytes) -> None:
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".graphvon-launcher-", dir=hook.parent)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o700)
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, hook, follow_symlinks=False)
        os.unlink(temporary); temporary = None
        directory = os.open(hook.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    except OSError: raise Refusal("Hook installation unavailable.") from None
    finally:
        if temporary is not None:
            try: os.unlink(temporary)
            except OSError: pass


def _partial(path: Path, expected: str) -> dict:
    """Report only attributable observed lifecycle state after a failed mutation."""
    state = "unknown"
    try:
        observed = _load(path)
        if observed["installation_id"] == expected: state = observed["lifecycle"]
    except (Refusal, OSError, ValueError, TypeError):
        pass
    return {"status": "unavailable", "installation_id": expected,
            "observed_lifecycle": state, "installation_verified": False}


def _unlink_owned(path: Path, expected: bytes) -> None:
    if read_ordinary(path) != expected: raise Refusal("Owned file changed.")
    path.unlink()
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)


def lifecycle(operation: str, request: dict) -> dict:
    try:
        if operation == "install":
            obj(request, {"version", "checkout", "policy", "intent"}, {"expected_installation_id"})
            allowed = {"create", "verify", "finish_install", "update_policy"}
        elif operation == "uninstall":
            obj(request, {"version", "checkout", "intent", "expected_installation_id"}); allowed = {"remove", "finish_removal"}
        else: raise InvalidInput("Invalid lifecycle operation.")
        if type(request["version"]) is not int or request["version"] != 1 or request["intent"] not in allowed: raise InvalidInput("Invalid lifecycle request.")
    except Refusal: raise InvalidInput("Invalid lifecycle request.") from None
    intent = request["intent"]
    if (intent == "create") != ("expected_installation_id" not in request): raise InvalidInput("Installation identity required.")
    root, gitdir, common = identity(_path(request["checkout"]))
    profile(root, gitdir, common)
    if git(root, "config", "--name-only", "--get-regexp", r"^core\.hookspath$", allow_missing=True).strip(): raise Unsupported("Configured hook path unsupported.")
    hook = common / "hooks" / "pre-push"; binding_path = gitdir / "graphvon" / "push-binding.json"
    if hook.parent.is_symlink() or not hook.parent.is_dir(): raise Unsupported("Unsupported hook directory.")
    if intent == "create":
        policy_path = _path(request["policy"]); data = read_ordinary(policy_path); policy_from_bytes(data, root)
        if not _absent(hook) or not _absent(binding_path): raise Unsupported("Hook slot or binding occupied.")
        try: binding_path.parent.mkdir(mode=0o700, exist_ok=True)
        except OSError: raise Refusal("Binding directory unavailable.") from None
        if binding_path.parent.is_symlink() or not binding_path.parent.is_dir(): raise Refusal("Unsupported binding directory.")
        binding = {"version": 1, "installation_id": str(uuid.uuid4()), "checkout": str(root), "git_directory": str(gitdir),
                   "common_directory": str(common), "policy_path": str(policy_path), "policy_sha256": sha(data),
                   "launcher_path": str(hook), "binding_path": str(binding_path), "lifecycle": "installing", "launcher_sha256": ""}
        binding["launcher_sha256"] = sha(launcher(binding))
        try:
            _save(binding_path, binding, create=True)
            _install_hook(hook, launcher(binding))
            _owned(binding, root, gitdir, common, binding_path, hook, binding["installation_id"])
            previous = deepcopy(binding); binding["lifecycle"] = "active"; _save(binding_path, binding, expected=previous)
        except (Refusal, OSError):
            return _partial(binding_path, binding["installation_id"])
        return {"status": "active", "installation_id": binding["installation_id"]}
    binding = _load(binding_path); expected = text(request["expected_installation_id"])
    _owned(binding, root, gitdir, common, binding_path, hook, expected)
    state = binding["lifecycle"]
    if intent in {"verify", "update_policy"} and (state != "active" or _absent(hook)): raise Refusal("Installation is not active.")
    if intent == "finish_install":
        if state != "installing": raise Refusal("No interrupted installation.")
        data = read_ordinary(_path(binding["policy_path"]))
        if sha(data) != binding["policy_sha256"]: raise Refusal("Policy changed.")
        policy_from_bytes(data, root)
        try:
            if _absent(hook): _install_hook(hook, launcher(binding))
            _owned(binding, root, gitdir, common, binding_path, hook, expected)
            previous = deepcopy(binding); binding["lifecycle"] = "active"; _save(binding_path, binding, expected=previous)
        except (Refusal, OSError):
            return _partial(binding_path, expected)
    elif intent == "verify":
        data = read_ordinary(_path(binding["policy_path"]))
        if str(_path(request["policy"])) != binding["policy_path"] or sha(data) != binding["policy_sha256"]: raise Refusal("Policy binding changed.")
        policy_from_bytes(data, root)
    elif intent == "update_policy":
        policy_path = _path(request["policy"]); data = read_ordinary(policy_path); policy_from_bytes(data, root)
        _owned(binding, root, gitdir, common, binding_path, hook, expected)
        previous = deepcopy(binding); binding["policy_path"] = str(policy_path); binding["policy_sha256"] = sha(data)
        try: _save(binding_path, binding, expected=previous)
        except (Refusal, OSError): return _partial(binding_path, expected)
    elif intent in {"remove", "finish_removal"}:
        if intent == "remove" and (state != "active" or _absent(hook)): raise Refusal("No active installation.")
        if intent == "finish_removal" and state != "removing": raise Refusal("No interrupted removal.")
        try:
            if intent == "remove":
                previous = deepcopy(binding); binding["lifecycle"] = "removing"; _save(binding_path, binding, expected=previous)
            if not _absent(hook):
                _owned(binding, root, gitdir, common, binding_path, hook, expected); _unlink_owned(hook, launcher(binding))
            current = _load(binding_path); _owned(current, root, gitdir, common, binding_path, hook, expected)
            current_bytes = read_ordinary(binding_path)
            if parse_json(current_bytes.decode("utf-8")) != current: raise Refusal("Binding ownership changed.")
            _unlink_owned(binding_path, current_bytes)
        except (Refusal, OSError):
            return _partial(binding_path, expected)
        return {"status": "removed", "installation_id": expected}
    return {"status": "active", "installation_id": expected}


def installed_pre_push(installation_id: str, adopted_root: str, adopted_git_directory: str, adopted_common_directory: str,
                       binding_path: str, launcher_path: str, remote_name: str, remote_location: str, update_stream: bytes) -> dict:
    root, gitdir, common = identity(Path.cwd())
    if str(common) == adopted_common_directory and str(gitdir) != adopted_git_directory:
        return {"status": "not_adopted", "invocation": "installed", "installation_verified": False}
    if str(root) != adopted_root or str(gitdir) != adopted_git_directory or str(common) != adopted_common_directory: raise Refusal("Checkout identity differs.")
    binding_file, hook = _path(binding_path), _path(launcher_path)
    binding = _load(binding_file); _owned(binding, root, gitdir, common, binding_file, hook, installation_id)
    if binding["lifecycle"] != "active" or _absent(hook): raise Refusal("Installation inactive.")
    data = read_ordinary(_path(binding["policy_path"]))
    if sha(data) != binding["policy_sha256"]: raise Refusal("Policy binding changed.")
    policy = policy_from_bytes(data, root)
    result = check_push(root, policy, update_stream)
    result.update(invocation="installed", installation_verified=True)
    return result


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) != 9 or args[0] != "--installed": raise Refusal("Invalid installed invocation.")
        result = installed_pre_push(*args[1:], sys.stdin.buffer.read())
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result["status"] == "literal_found" else 0
    except InvalidInput:
        print(json.dumps({"status": "invalid_input", "invocation": "installed", "installation_verified": False}))
        return 2
    except Unsupported:
        print(json.dumps({"status": "unsupported", "invocation": "installed", "installation_verified": False}))
        return 2
    except (Refusal, OSError, ValueError, TypeError, RecursionError):
        print(json.dumps({"status": "unavailable", "invocation": "installed", "installation_verified": False}))
        return 2


if __name__ == "__main__": raise SystemExit(main())

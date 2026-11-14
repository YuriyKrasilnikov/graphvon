"""Scoped lifecycle ownership and installed versus standalone behavior."""

import json
import os
from pathlib import Path
import subprocess
import stat
from unittest.mock import patch
import tempfile
import unittest

from graphvon.contracts import Refusal
from graphvon.push_installation import _install_hook, installed_pre_push, lifecycle
from graphvon.push_check import check_push
from test_push_check import git


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name) / "repo"; self.root.mkdir()
        git(self.root, "init", "-q")
        self.policy = Path(self.temp.name) / "policy.json"
        self.policy.write_text(json.dumps({"version": 1, "checkout": str(self.root.resolve()), "destinations": "all", "owner": "fixture",
            "authority": [{"locator": "fixture", "description": "fixture"}], "protected_literals": []}))

    def tearDown(self): self.temp.cleanup()

    def test_create_verify_and_remove_owned_launcher(self):
        created = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        ident = created["installation_id"]
        result = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "verify", "expected_installation_id": ident})
        self.assertEqual(result["status"], "active")
        result = lifecycle("uninstall", {"version": 1, "checkout": str(self.root), "expected_installation_id": ident, "intent": "remove"})
        self.assertEqual(result["status"], "removed")

    def test_foreign_hook_is_not_overwritten(self):
        hook = self.root / ".git/hooks/pre-push"; hook.write_text("foreign")
        with self.assertRaises(Refusal):
            lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        self.assertEqual(hook.read_text(), "foreign")

    def test_installed_local_push_refuses_literal_and_accepts_clean_mapping(self):
        self.policy.write_text(json.dumps({"version": 1, "checkout": str(self.root.resolve()), "destinations": "all", "owner": "fixture",
            "authority": [{"locator": "fixture", "description": "fixture"}], "protected_literals": [{"id": "fixture", "value": "SYNTHETIC-PRIVATE-TOKEN",
            "owner": "fixture", "sources": [{"locator": "fixture", "description": "fixture"}], "applicability": "fixture", "retirement_condition": "fixture"}]}))
        remote = Path(self.temp.name) / "remote.git"; subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        git(self.root, "checkout", "-qb", "SYNTHETIC-PRIVATE-TOKEN")
        (self.root / "file").write_text("public")
        git(self.root, "add", "file"); git(self.root, "commit", "-qm", "initial")
        lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        run = subprocess.run(["git", "-C", str(self.root), "push", str(remote), "HEAD:refs/heads/public"], capture_output=True, env=env)
        self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
        original = git(remote, "rev-parse", "refs/heads/public")
        (self.root / "file").write_text("SYNTHETIC-PRIVATE-TOKEN")
        git(self.root, "add", "file"); git(self.root, "commit", "-qm", "update")
        run = subprocess.run(["git", "-C", str(self.root), "push", str(remote), "HEAD:refs/heads/public"], capture_output=True, env=env)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(git(remote, "rev-parse", "refs/heads/public"), original)

    def test_interrupted_installation_requires_matching_identity_and_finishes(self):
        with patch("graphvon.push_installation._install_hook", side_effect=Refusal("interrupted")):
            partial = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        self.assertEqual(partial["status"], "unavailable")
        self.assertEqual(partial["observed_lifecycle"], "installing")
        binding = json.loads((self.root / ".git/graphvon/push-binding.json").read_text())
        self.assertEqual(binding["lifecycle"], "installing")
        request = {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "finish_install", "expected_installation_id": "wrong"}
        with self.assertRaises(Refusal): lifecycle("install", request)
        request["expected_installation_id"] = binding["installation_id"]
        self.assertEqual(lifecycle("install", request)["status"], "active")

    def test_midwrite_interruption_leaves_no_partial_visible_hook_and_recovers(self):
        hook = self.root / ".git/hooks/pre-push"
        original_fdopen = os.fdopen

        class InterruptingWriter:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): self.stream.__enter__(); return self
            def __exit__(self, *args): return self.stream.__exit__(*args)
            def __getattr__(self, name): return getattr(self.stream, name)
            def write(self, data):
                if data.startswith(b"#!/bin/sh\n"):
                    self.stream.write(b"#!/bin/sh\n"); self.stream.flush()
                    raise OSError("synthetic write interruption")
                return self.stream.write(data)

        def intercept(fd, mode, *args, **kwargs):
            stream = original_fdopen(fd, mode, *args, **kwargs)
            return InterruptingWriter(stream) if mode == "wb" else stream

        with patch("graphvon.push_installation.os.fdopen", side_effect=intercept):
            partial = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        self.assertEqual(partial["status"], "unavailable")
        self.assertEqual(partial["observed_lifecycle"], "installing")
        self.assertFalse(hook.exists())
        request = {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "finish_install", "expected_installation_id": partial["installation_id"]}
        self.assertEqual(lifecycle("install", request)["status"], "active")
        self.assertTrue(hook.read_bytes().startswith(b"#!/bin/sh\nexec "))
        request["intent"] = "verify"
        self.assertEqual(lifecycle("install", request)["status"], "active")

    def test_interruption_after_publication_retains_exact_owned_hook(self):
        hook = self.root / ".git/hooks/pre-push"
        directory_stat = hook.parent.stat()
        original_fsync = os.fsync

        def interrupted(fd):
            observed = os.fstat(fd)
            if stat.S_ISDIR(observed.st_mode) and (observed.st_dev, observed.st_ino) == (directory_stat.st_dev, directory_stat.st_ino):
                raise OSError("synthetic directory sync interruption")
            return original_fsync(fd)

        with patch("graphvon.push_installation.os.fsync", side_effect=interrupted):
            partial = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        self.assertEqual(partial["status"], "unavailable")
        self.assertEqual(partial["observed_lifecycle"], "installing")
        published = hook.read_bytes()
        self.assertTrue(published.startswith(b"#!/bin/sh\nexec "))
        request = {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "finish_install", "expected_installation_id": partial["installation_id"]}
        self.assertEqual(lifecycle("install", request)["status"], "active")
        self.assertEqual(hook.read_bytes(), published)

    def test_changed_policy_requires_deliberate_update(self):
        created = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        self.policy.write_text(self.policy.read_text() + "\n")
        request = {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "verify", "expected_installation_id": created["installation_id"]}
        with self.assertRaises(Refusal): lifecycle("install", request)
        request["intent"] = "update_policy"
        self.assertEqual(lifecycle("install", request)["status"], "active")
        request["intent"] = "verify"
        self.assertEqual(lifecycle("install", request)["status"], "active")

    def test_standalone_can_examine_changed_policy_but_installed_refuses(self):
        created = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        binding_path = self.root / ".git/graphvon/push-binding.json"; binding = json.loads(binding_path.read_text())
        self.policy.write_text(self.policy.read_text() + "\n")
        self.assertEqual(check_push(self.root, json.loads(self.policy.read_text()), b"")["status"], "checked")
        original = Path.cwd()
        try:
            os.chdir(self.root)
            with self.assertRaises(Refusal):
                installed_pre_push(created["installation_id"], binding["checkout"], binding["git_directory"], binding["common_directory"],
                                   str(binding_path), binding["launcher_path"], "origin", "example", b"")
        finally: os.chdir(original)

    def test_hook_appearing_during_install_is_preserved(self):
        hook = self.root / ".git/hooks/pre-push"
        def collision(path, data):
            path.write_text("foreign")
            return _install_hook(path, data)
        with patch("graphvon.push_installation._install_hook", side_effect=collision):
            partial = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        self.assertEqual(partial["status"], "unavailable")
        self.assertEqual(hook.read_text(), "foreign")
        self.assertEqual(json.loads((self.root / ".git/graphvon/push-binding.json").read_text())["lifecycle"], "installing")

    def test_unadopted_linked_worktree_skips_before_missing_policy(self):
        (self.root / "file").write_text("public"); git(self.root, "add", "file"); git(self.root, "commit", "-qm", "initial")
        other = Path(self.temp.name) / "linked"
        git(self.root, "worktree", "add", "-qb", "other", str(other))
        created = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        binding_path = self.root / ".git/graphvon/push-binding.json"; binding = json.loads(binding_path.read_text())
        self.policy.unlink()
        original = Path.cwd()
        try:
            os.chdir(other)
            result = installed_pre_push(created["installation_id"], binding["checkout"], binding["git_directory"], binding["common_directory"],
                                        str(binding_path), binding["launcher_path"], "origin", "example", b"")
        finally: os.chdir(original)
        self.assertEqual(result["status"], "not_adopted")
        self.assertFalse(result["installation_verified"])

    def test_interrupted_removal_resumes_and_does_not_remove_policy(self):
        created = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        request = {"version": 1, "checkout": str(self.root), "expected_installation_id": created["installation_id"], "intent": "remove"}
        hook = self.root / ".git/hooks/pre-push"; original_unlink = Path.unlink
        def interrupted(path, *args, **kwargs):
            if path == hook: raise OSError("interrupted")
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", interrupted):
            partial = lifecycle("uninstall", request)
        self.assertEqual(partial["status"], "unavailable")
        self.assertEqual(partial["observed_lifecycle"], "removing")
        binding = json.loads((self.root / ".git/graphvon/push-binding.json").read_text())
        self.assertEqual(binding["lifecycle"], "removing")
        request["intent"] = "finish_removal"
        self.assertEqual(lifecycle("uninstall", request)["status"], "removed")
        self.assertTrue(self.policy.exists())

    def test_modified_or_nonexecutable_owned_hook_is_not_accepted(self):
        created = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        hook = self.root / ".git/hooks/pre-push"; hook.chmod(0o600)
        request = {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "verify", "expected_installation_id": created["installation_id"]}
        with self.assertRaises(Refusal): lifecycle("install", request)
        self.assertTrue(hook.exists())

    def test_modified_launcher_cannot_be_replaced_via_policy_update(self):
        created = lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        hook = self.root / ".git/hooks/pre-push"; hook.write_text("foreign replacement")
        request = {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "update_policy", "expected_installation_id": created["installation_id"]}
        with self.assertRaises(Refusal): lifecycle("install", request)
        self.assertEqual(hook.read_text(), "foreign replacement")

    def test_configured_hook_path_is_preserved_and_refused(self):
        git(self.root, "config", "core.hooksPath", "custom-hooks")
        with self.assertRaises(Refusal):
            lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})
        self.assertEqual(git(self.root, "config", "--get", "core.hooksPath"), b"custom-hooks")
        git(self.root, "config", "core.hooksPath", "")
        with self.assertRaises(Refusal):
            lifecycle("install", {"version": 1, "checkout": str(self.root), "policy": str(self.policy), "intent": "create"})

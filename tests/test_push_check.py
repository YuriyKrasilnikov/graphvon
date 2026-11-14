"""Controlled Git publication behavior, using synthetic private literals."""

import os
from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from graphvon.push_check import check_push, main
from graphvon.contracts import Refusal


def git(root, *args, input=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
           "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"}
    return subprocess.run(["git", "-C", str(root), *args], input=input, capture_output=True, check=True, env=env).stdout.strip()


class PushScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        self.policy = {"version": 1, "checkout": str(self.root.resolve()), "destinations": "all", "owner": "fixture",
                       "authority": [{"locator": "fixture", "description": "fixture"}], "protected_literals": [
                           {"id": "private", "value": "SYNTHETIC-PRIVATE-TOKEN", "owner": "fixture",
                            "sources": [{"locator": "fixture", "description": "fixture"}], "applicability": "fixture", "retirement_condition": "fixture"}]}

    def tearDown(self): self.temp.cleanup()

    def commit(self, name, data, message):
        (self.root / name).write_bytes(data)
        git(self.root, "add", "--", name); git(self.root, "commit", "-qm", message)
        return git(self.root, "rev-parse", "HEAD").decode()

    def test_intermediate_secret_refused_even_when_final_tree_clean(self):
        self.commit("file", b"SYNTHETIC-PRIVATE-TOKEN", "first")
        oid = self.commit("file", b"public", "second")
        updates = f"refs/heads/private-local {oid} refs/heads/public {'0'*40}\n".encode()
        result = check_push(self.root, self.policy, updates)
        self.assertEqual(result["status"], "literal_found")

    def test_clean_content_and_private_local_ref_are_permitted(self):
        oid = self.commit("file", b"public", "ordinary")
        updates = f"refs/heads/SYNTHETIC-PRIVATE-TOKEN {oid} refs/heads/public {'0'*40}\n".encode()
        result = check_push(self.root, self.policy, updates)
        self.assertEqual(result["status"], "checked")
        self.assertEqual(result["invocation"], "standalone")
        self.assertFalse(result["installation_verified"])

    def test_complete_old_closure_is_excluded_but_new_names_are_inspected(self):
        old = self.commit("file", b"SYNTHETIC-PRIVATE-TOKEN", "old")
        new = self.commit("another", b"public", "new")
        updates = f"refs/heads/local {new} refs/heads/public {old}\n".encode()
        self.assertEqual(check_push(self.root, self.policy, updates)["status"], "checked")
        git(self.root, "mv", "file", "SYNTHETIC-PRIVATE-TOKEN")
        git(self.root, "commit", "-qm", "rename")
        renamed = git(self.root, "rev-parse", "HEAD").decode()
        updates = f"refs/heads/local {renamed} refs/heads/public {new}\n".encode()
        self.assertEqual(check_push(self.root, self.policy, updates)["status"], "literal_found")

    def test_binary_literal_across_chunk_boundary_is_detected(self):
        token = b"SYNTHETIC-PRIVATE-TOKEN"
        oid = self.commit("binary", b"x" * 65530 + token + b"\0", "binary")
        updates = f"refs/heads/local {oid} refs/heads/public {'0'*40}\n".encode()
        self.assertEqual(check_push(self.root, self.policy, updates)["status"], "literal_found")

    def test_removed_intermediate_filename_is_detected(self):
        self.commit("SYNTHETIC-PRIVATE-TOKEN", b"public", "first")
        git(self.root, "rm", "SYNTHETIC-PRIVATE-TOKEN"); git(self.root, "commit", "-qm", "remove")
        oid = git(self.root, "rev-parse", "HEAD").decode()
        line = f"refs/heads/local {oid} refs/heads/public {'0'*40}\n".encode()
        self.assertEqual(check_push(self.root, self.policy, line)["status"], "literal_found")

    def test_mixed_delete_does_not_scan_its_name(self):
        old = self.commit("file", b"public", "initial")
        new = self.commit("file", b"new public", "new")
        stream = (f"(delete) {'0'*40} refs/heads/SYNTHETIC-PRIVATE-TOKEN {old}\n"
                  f"refs/heads/local {new} refs/heads/public {old}\n").encode()
        self.assertEqual(check_push(self.root, self.policy, stream)["status"], "checked")

    def test_deletion_does_not_scan_destination_name(self):
        oid = self.commit("file", b"public", "ordinary")
        updates = f"(delete) {'0'*40} refs/heads/SYNTHETIC-PRIVATE-TOKEN {oid}\n".encode()
        self.assertEqual(check_push(self.root, self.policy, updates)["status"], "checked")

    def test_nonzero_unavailable_old_root_does_not_hide_new_content(self):
        oid = self.commit("file", b"SYNTHETIC-PRIVATE-TOKEN", "ordinary")
        updates = f"refs/heads/local {oid} refs/heads/public {'f'*40}\n".encode()
        self.assertEqual(check_push(self.root, self.policy, updates)["status"], "literal_found")

    def test_tag_message_and_symlink_target_are_scanned(self):
        oid = self.commit("file", b"public", "ordinary")
        git(self.root, "tag", "-a", "release", "-m", "SYNTHETIC-PRIVATE-TOKEN")
        tag = git(self.root, "rev-parse", "refs/tags/release").decode()
        line = f"refs/tags/release {tag} refs/tags/release {'0'*40}\n".encode()
        self.assertEqual(check_push(self.root, self.policy, line)["status"], "literal_found")
        (self.root / "link").symlink_to("SYNTHETIC-PRIVATE-TOKEN")
        git(self.root, "add", "link"); git(self.root, "commit", "-qm", "link")
        new = git(self.root, "rev-parse", "HEAD").decode()
        line = f"refs/heads/local {new} refs/heads/public {oid}\n".encode()
        self.assertEqual(check_push(self.root, self.policy, line)["status"], "literal_found")

    def test_nested_annotated_tag_is_supported(self):
        self.commit("file", b"public", "ordinary")
        git(self.root, "tag", "-a", "first", "-m", "release")
        git(self.root, "tag", "-a", "second", "first", "-m", "outer")
        tag = git(self.root, "rev-parse", "refs/tags/second").decode()
        line = f"refs/tags/second {tag} refs/tags/second {'0'*40}\n".encode()
        self.assertEqual(check_push(self.root, self.policy, line)["status"], "checked")

    def test_invalid_cli_arguments_do_not_echo_sensitive_text(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["check", "--unknown", "SYNTHETIC-PRIVATE-TOKEN"])
        self.assertEqual(result, 2)
        self.assertNotIn("SYNTHETIC-PRIVATE-TOKEN", output.getvalue())

    def test_invalid_lifecycle_json_is_reported_without_echo(self):
        output = io.StringIO()
        with redirect_stdout(output), patch.object(sys, "stdin", io.StringIO("{SYNTHETIC-PRIVATE-TOKEN")):
            result = main(["install"])
        self.assertEqual(result, 2)
        self.assertIn("invalid_input", output.getvalue())
        self.assertNotIn("SYNTHETIC-PRIVATE-TOKEN", output.getvalue())

    def test_sha256_repository_if_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            init = subprocess.run(["git", "-C", str(root), "init", "-q", "--object-format=sha256"], capture_output=True)
            if init.returncode: self.skipTest("Git lacks SHA-256 repository support")
            (root / "file").write_bytes(b"SYNTHETIC-PRIVATE-TOKEN")
            git(root, "add", "file"); git(root, "commit", "-qm", "initial")
            oid = git(root, "rev-parse", "HEAD").decode()
            policy = {**self.policy, "checkout": str(root.resolve())}
            line = f"refs/heads/local {oid} refs/heads/public {'0'*64}\n".encode()
            self.assertEqual(check_push(root, policy, line)["status"], "literal_found")

    def test_literal_with_nul_is_scanned_and_diagnostic_does_not_echo_it(self):
        self.policy["protected_literals"][0]["value"] = "alpha\u0000beta"
        oid = self.commit("binary", b"before alpha\0beta after", "ordinary")
        result = check_push(self.root, self.policy, f"refs/heads/local {oid} refs/heads/public {'0'*40}\n".encode())
        self.assertEqual(result["status"], "literal_found")
        self.assertNotIn("alpha", str(result))

    def test_entry_id_cannot_echo_a_protected_literal(self):
        self.policy["protected_literals"][0]["value"] = "privateword"
        self.policy["protected_literals"][0]["id"] = "privateword"
        oid = self.commit("file", b"privateword", "ordinary")
        result = check_push(self.root, self.policy, f"refs/heads/local {oid} refs/heads/public {'0'*40}\n".encode())
        self.assertEqual(result["status"], "literal_found")
        self.assertNotIn("privateword", str(result))

    def test_gitlink_reference_is_scanned_without_reading_external_objects(self):
        self.policy["protected_literals"][0]["value"] = "a" * 40
        git(self.root, "update-index", "--add", "--cacheinfo", "160000," + "a" * 40 + ",submodule")
        git(self.root, "commit", "-qm", "gitlink")
        oid = git(self.root, "rev-parse", "HEAD").decode()
        line = f"refs/heads/local {oid} refs/heads/public {'0'*40}\n".encode()
        self.assertEqual(check_push(self.root, self.policy, line)["status"], "literal_found")

    def test_invalid_protocol_and_replacement_refs_are_refused(self):
        oid = self.commit("file", b"public", "ordinary")
        with self.assertRaises(Refusal): check_push(self.root, self.policy, b"malformed\n")
        git(self.root, "update-ref", "refs/replace/" + oid, oid)
        line = f"refs/heads/local {oid} refs/heads/public {'0'*40}\n".encode()
        with self.assertRaises(Refusal): check_push(self.root, self.policy, line)

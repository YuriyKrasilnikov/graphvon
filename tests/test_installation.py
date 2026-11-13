"""Private binding checks with real local Git roots and synthetic records."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from graphvon import hook
from graphvon.contracts import Grant, Refusal, scope_digest
from graphvon.installation import resolve_installation


class InstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="graphvon-installation-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.root = self.directory / "checkout"
        self.git("init", "--quiet", str(self.root))
        self.git("-C", str(self.root), "remote", "add", "origin", "https://github.com/example/project.git")
        self.config_home = self.directory / "config"
        self.config_path = self.config_home / "graphvon/config.toml"
        self.config_path.parent.mkdir(parents=True)
        self.context_path = self.directory / "context.json"
        self.working_record = self.directory / "working.md"
        self.working_record.write_text("PRIVATE WORKING CONTENT", encoding="utf-8")
        self.record = self.write_context(self.context_path, self.root)
        environment = {"HOME": str(self.directory), "XDG_CONFIG_HOME": str(self.config_home),
                       "PATH": os.environ.get("PATH", os.defpath)}
        self.environment = patch.dict(os.environ, environment, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.register()

    def git(self, *arguments):
        subprocess.run(["git", *arguments], check=True, capture_output=True, text=True)

    def write_context(self, path, root):
        grants = (Grant("add", "sample.txt"),)
        effect = "Prepare a synthetic fixture"
        record = {
            "version": 1, "kind": "preparation", "root": str(root),
            "repository": {"name": "example/project", "id": "R_example", "remote": "origin"},
            "owner": "synthetic-owner", "generation": "PRIVATE GENERATION", "effect": effect,
            "grants": [asdict(grant) for grant in grants],
            "admission": {"reference": "PRIVATE ADMISSION", "sha256": "a" * 64,
                          "scope_sha256": scope_digest("preparation", effect, grants)},
        }
        path.write_text(json.dumps(record), encoding="utf-8")
        return record

    def register(self, root=None, context=None):
        text = ("version = 1\n[projects." + json.dumps(str(root or self.root)) + "]\n"
                + "context = " + json.dumps(str(context or self.context_path)) + "\n"
                + "working_record = " + json.dumps(str(self.working_record)) + "\n")
        self.config_path.write_text(text, encoding="utf-8")
        return text

    def resolve(self, cwd=None):
        return resolve_installation(cwd or self.root, time.monotonic() + 5)

    def invoke(self, event, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(event))), redirect_stdout(stdout), redirect_stderr(stderr):
            code = hook.main(list(arguments))
        self.assertEqual((code, stderr.getvalue()), (0, ""))
        return json.loads(stdout.getvalue())

    def test_exact_registration_uses_event_cwd_and_preserves_records(self):
        child = self.root / "subdirectory"
        child.mkdir()
        before = {path: path.read_bytes() for path in (self.config_path, self.context_path, self.working_record)}
        result = self.resolve(child)
        self.assertEqual(result.context.root, self.root)
        self.assertEqual(result.context_path, self.context_path)
        self.assertEqual(result.working_record, self.working_record)
        self.assertEqual(result.skill_path, self.root / ".agents/skills/graphvon-start-work/SKILL.md")
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_default_configuration_location_and_empty_xdg(self):
        default = self.directory / ".config/graphvon/config.toml"
        default.parent.mkdir(parents=True)
        default.write_bytes(self.config_path.read_bytes())
        self.config_path.unlink()
        for value in (None, ""):
            with self.subTest(value=value):
                os.environ.pop("XDG_CONFIG_HOME", None)
                if value is not None:
                    os.environ["XDG_CONFIG_HOME"] = value
                self.assertEqual(self.resolve().context_path, self.context_path)

    def test_relative_configuration_home_is_refused(self):
        os.environ["XDG_CONFIG_HOME"] = "relative"
        with self.assertRaises(Refusal):
            self.resolve()

    def test_absent_configuration_or_registration_is_refused(self):
        self.config_path.unlink()
        with self.assertRaises(Refusal):
            self.resolve()
        self.config_path.write_text("version = 1\n[projects]\n", encoding="utf-8")
        with self.assertRaises(Refusal):
            self.resolve()

    def test_malformed_toml_types_fields_and_paths_are_refused(self):
        valid = self.config_path.read_text()
        invalid = ["[", "version = 1\nversion = 1\n[projects]\n",
                   valid.replace("version = 1", "version = true"),
                   valid.replace("version = 1", "version = 2"),
                   "version = 1\nprojects = []\n", "projects = {}\n",
                   "extra = 1\n" + valid, valid + "extra = 1\n",
                   valid.replace("working_record =", "wrong_field ="),
                   valid.replace(json.dumps(str(self.context_path)), "42"),
                   valid.replace(json.dumps(str(self.working_record)), '"relative.md"'),
                   valid.replace(json.dumps(str(self.root)), '"relative"'),
                   valid.replace(json.dumps(str(self.root)), json.dumps(str(self.root) + "/../checkout"))]
        for text in invalid:
            with self.subTest(text=text):
                self.config_path.write_text(text, encoding="utf-8")
                with self.assertRaises(Refusal):
                    self.resolve()
        self.config_path.write_bytes(b"\xff")
        with self.assertRaises(Refusal):
            self.resolve()

    def test_nonregular_configuration_refuses_without_waiting_for_a_writer(self):
        script = ("from pathlib import Path\nimport time\n"
                  "from graphvon.contracts import Refusal\n"
                  "from graphvon.installation import resolve_installation\n"
                  "try:\n resolve_installation(Path(" + repr(str(self.root)) + "), time.monotonic()+2)\n"
                  "except Refusal:\n pass\nelse:\n raise AssertionError('accepted nonregular config')\n")
        for kind in ("directory", "fifo"):
            with self.subTest(kind=kind):
                self.config_path.unlink()
                if kind == "directory":
                    self.config_path.mkdir()
                else:
                    os.mkfifo(self.config_path)
                environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
                result = subprocess.run([sys.executable, "-c", script], env=environment,
                                        capture_output=True, text=True, timeout=3)
                self.assertEqual(result.returncode, 0, result.stderr)
                if kind == "directory":
                    self.config_path.rmdir()
                    self.config_path.touch()

    def test_configuration_descriptors_close_on_success_and_parse_failure(self):
        descriptors = Path("/proc/self/fd")
        if not descriptors.is_dir():
            self.skipTest("Descriptor observation is unavailable")
        before = len(list(descriptors.iterdir()))
        for _ in range(5):
            self.resolve()
        self.config_path.write_text("[", encoding="utf-8")
        for _ in range(5):
            with self.assertRaises(Refusal):
                self.resolve()
        self.assertEqual(len(list(descriptors.iterdir())), before)

    def test_valid_override_is_independent_of_broken_registration(self):
        alternate = self.directory / "override.json"
        self.write_context(alternate, self.root)
        os.environ["GRAPHVON_CONTEXT"] = str(alternate)
        self.config_path.write_text("[", encoding="utf-8")
        result = self.resolve()
        self.assertEqual(result.context_path, alternate)
        self.assertIsNone(result.working_record)

    def test_invalid_override_never_falls_back_to_valid_registration(self):
        invalid = self.directory / "invalid.json"
        invalid.write_text("{", encoding="utf-8")
        wrong = self.directory / "wrong.json"
        self.write_context(wrong, self.directory)
        for value in ("", "relative.json", str(self.directory / "missing.json"), str(invalid), str(wrong)):
            with self.subTest(value=value):
                os.environ["GRAPHVON_CONTEXT"] = value
                with self.assertRaises(Refusal):
                    self.resolve()

    def test_registered_context_must_validate_and_match_the_exact_root(self):
        for text in ("{", json.dumps({**self.record, "root": str(self.directory)})):
            self.context_path.write_text(text, encoding="utf-8")
            with self.assertRaises(Refusal):
                self.resolve()

    def test_sibling_and_nested_repositories_do_not_inherit_a_registration(self):
        for root in (self.directory / "checkout-other", self.root / "nested"):
            self.git("init", "--quiet", str(root))
            with self.subTest(root=root), self.assertRaises(Refusal):
                self.resolve(root)
        self.register(root=self.directory)
        with self.assertRaises(Refusal):
            self.resolve()

    def test_canonical_root_registration_resolves_a_symlinked_cwd(self):
        alias = self.directory / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.resolve(alias).context.root, self.root)
        self.register(root=alias)
        with self.assertRaises(Refusal):
            self.resolve()

    def test_invalid_cwd_and_expired_deadline_are_refused(self):
        for cwd in (Path("relative"), self.directory / "missing", self.directory):
            with self.subTest(cwd=cwd), self.assertRaises(Refusal):
                self.resolve(cwd)
        with self.assertRaises(Refusal):
            resolve_installation(self.root, time.monotonic() - 1)

    def test_session_and_pretool_share_registration_without_exposing_record_contents(self):
        before = self.context_path.read_bytes()
        for source in ("startup", "resume", "clear", "compact", "fork"):
            result = self.invoke({"hook_event_name": "SessionStart", "source": source,
                                  "cwd": str(self.root)}, "session-start")
            message = result["hookSpecificOutput"]["additionalContext"]
            self.assertIn(str(self.context_path), message)
            self.assertIn(str(self.working_record), message)
            self.assertNotIn("PRIVATE", message)
        native_repository = {"id": 1, "node_id": "R_example", "full_name": "example/project"}
        event = {"hook_event_name": "PreToolUse", "tool_name": "apply_patch", "cwd": str(self.root),
                 "tool_input": {"command": "*** Begin Patch\n*** Add File: sample.txt\n+fixture\n*** End Patch"}}
        with patch("graphvon.sources._read", return_value=native_repository):
            self.assertEqual(self.invoke(event), {})
            event["tool_input"]["command"] = event["tool_input"]["command"].replace("sample.txt", "outside.txt")
            self.assertEqual(self.invoke(event)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.context_path.read_bytes(), before)
        self.assertFalse((self.root / "sample.txt").exists())
        self.write_context(self.context_path, self.directory)
        result = self.invoke({"hook_event_name": "SessionStart", "source": "resume",
                              "cwd": str(self.root)}, "session-start")
        message = result["hookSpecificOutput"]["additionalContext"]
        self.assertIn("unavailable", message)
        self.assertNotIn(str(self.directory), message)


if __name__ == "__main__":
    unittest.main()

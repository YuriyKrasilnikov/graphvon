"""Adapter checks with controlled readers and patch validation."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from graphvon import hook
from graphvon.contracts import Refusal
from graphvon.installation import Installation, resolve_installation


class HookTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.clock = self.stack.enter_context(patch.object(hook.time, "monotonic", return_value=100.0))
        self.context = SimpleNamespace(root=Path("/synthetic-checkout"), grants=(), kind="preparation")
        self.installation = Installation(Path("/synthetic-private/context.json"), self.context,
                                         Path("/synthetic-private/working.md"))
        self.resolve = self.stack.enter_context(
            patch.object(hook, "resolve_installation", return_value=self.installation)
        )
        self.checkout = self.stack.enter_context(patch.object(hook, "check_checkout"))
        self.inspect = self.stack.enter_context(patch.object(hook, "inspect_patch", return_value=()))
        self.sources = self.stack.enter_context(patch.object(hook, "check_source_basis"))
        self.observe = self.stack.enter_context(patch.object(hook, "observe_basis"))
        self.event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "cwd": "/synthetic-checkout",
            "tool_input": {"command": "*** Begin Patch\n*** Delete File: sample.txt\n*** End Patch"},
            "tool_use_id": "synthetic-call",
        }

    def invoke(self, event=None, *, raw=None, argv=()):
        stdin = io.StringIO(raw if raw is not None else json.dumps(self.event if event is None else event))
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(hook.sys, "stdin", stdin), redirect_stdout(stdout), redirect_stderr(stderr):
            code = hook.main(list(argv))
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_denied(self, result):
        code, stdout, stderr = result
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        output = json.loads(stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertTrue(output["permissionDecisionReason"])
        self.assertNotIn("/synthetic-private", stdout)
        return output["permissionDecisionReason"]

    def test_permitted_patch_runs_all_checks_in_order_under_one_deadline(self):
        calls = []
        self.resolve.side_effect = lambda *args: calls.append("context") or self.installation
        self.checkout.side_effect = lambda *args: calls.append("checkout")
        self.inspect.side_effect = lambda *args: calls.append("patch") or ()
        self.sources.side_effect = lambda *args: calls.append("sources")

        code, stdout, stderr = self.invoke()

        self.assertEqual((code, json.loads(stdout), stderr), (0, {}, ""))
        self.assertEqual(calls, ["context", "checkout", "patch", "sources"])
        self.resolve.assert_called_once_with(Path("/synthetic-checkout"), 106.0)
        self.checkout.assert_called_once_with(self.context, Path("/synthetic-checkout"), 106.0)
        self.inspect.assert_called_once_with(
            self.event["tool_input"]["command"], Path("/synthetic-checkout"), self.context.root, ()
        )
        self.sources.assert_called_once_with(self.context, 106.0)
        self.observe.assert_not_called()

    def test_invalid_or_uncovered_events_are_denied_before_loading_context(self):
        events = [
            [],
            {**self.event, "hook_event_name": "PostToolUse"},
            {**self.event, "tool_name": "Bash"},
            {**self.event, "cwd": "relative"},
            {**self.event, "tool_input": {"command": []}},
            {**self.event, "tool_input": {}},
        ]
        for event in events:
            with self.subTest(event=event):
                self.assert_denied(self.invoke(event))
        self.resolve.assert_not_called()

    def test_unavailable_installation_denies_before_checkout_validation(self):
        self.resolve.side_effect = Refusal("Private registration could not be resolved")
        self.assert_denied(self.invoke())
        self.checkout.assert_not_called()

    def test_malformed_or_duplicate_json_is_denied(self):
        for raw in (
            "{",
            '{"tool_name":"apply_patch","tool_name":"Bash"}',
            json.dumps({**self.event, "metadata": float("nan")}),
        ):
            with self.subTest(raw=raw):
                self.assert_denied(self.invoke(raw=raw))
        self.resolve.assert_not_called()

    def test_refused_patch_never_reaches_source_validation(self):
        self.inspect.side_effect = Refusal("A private path must not be echoed: /synthetic-private/context.json")
        self.assert_denied(self.invoke())
        self.sources.assert_not_called()

    def test_failed_source_check_denies_without_exposing_exception_text(self):
        self.sources.side_effect = Refusal("/synthetic-private/context.json contains stale data")
        self.assert_denied(self.invoke())

    def test_context_read_error_is_an_explicit_denial(self):
        self.resolve.side_effect = OSError("Cannot read /synthetic-private/context.json")
        self.assert_denied(self.invoke())
        self.checkout.assert_not_called()

    def test_deadline_expiry_stops_dependent_checks(self):
        self.clock.side_effect = [100.0, 100.0, 100.0, 107.0]
        reason = self.assert_denied(self.invoke())
        self.assertIn("deadline", reason)
        self.inspect.assert_not_called()
        self.sources.assert_not_called()

    def test_unexpected_adapter_failure_does_not_become_allow(self):
        self.checkout.side_effect = RuntimeError("/synthetic-private/context.json")
        reason = self.assert_denied(self.invoke())
        self.assertIn("unavailable", reason)
        self.inspect.assert_not_called()

    def test_snapshot_only_reads_sources_without_context_or_authority(self):
        basis = {"complete": True, "repository": {"name": "example/project", "id": "R_example"}}
        self.observe.return_value = basis
        with patch.dict(os.environ, {}, clear=True):
            code, stdout, stderr = self.invoke(
                argv=("snapshot", "--repository", "example/project", "--issue", "2", "--pull", "4")
            )
        self.assertEqual((code, json.loads(stdout), stderr), (0, basis, ""))
        self.observe.assert_called_once_with("example/project", 2, 4, 106.0)
        self.resolve.assert_not_called()
        self.inspect.assert_not_called()

    def test_snapshot_failure_reports_no_basis_or_private_details(self):
        self.observe.side_effect = Refusal("/synthetic-private/context.json")
        code, stdout, stderr = self.invoke(
            argv=("snapshot", "--repository", "example/project", "--issue", "2", "--pull", "4")
        )
        self.assertEqual((code, stdout), (1, ""))
        self.assertNotIn("/synthetic-private", stderr)
        self.assertTrue(stderr)

    def test_all_session_sources_offer_only_local_references_without_admission(self):
        for source in ("startup", "resume", "clear", "compact", "fork"):
            with self.subTest(source=source):
                event = {"hook_event_name": "SessionStart", "source": source,
                         "cwd": "/synthetic-checkout"}
                code, stdout, stderr = self.invoke(event, argv=("session-start",))
                self.assertEqual((code, stderr), (0, ""))
                result = json.loads(stdout)
                self.assertEqual(set(result), {"hookSpecificOutput"})
                output = result["hookSpecificOutput"]
                self.assertEqual(set(output), {"hookEventName", "additionalContext"})
                self.assertEqual(output["hookEventName"], "SessionStart")
                message = output["additionalContext"]
                for path in (self.installation.context_path, self.installation.working_record,
                             self.installation.skill_path):
                    self.assertIn(str(path), message)
                self.assertIn("Reconcile", message)
                self.assertIn("no new authority", message)
        self.checkout.assert_not_called()
        self.inspect.assert_not_called()
        self.sources.assert_not_called()
        self.observe.assert_not_called()

    def test_invalid_session_events_do_not_resolve_private_state(self):
        event = {"hook_event_name": "SessionStart", "source": "startup",
                 "cwd": "/synthetic-checkout"}
        for invalid in ([], self.event, {**event, "source": "unknown"},
                        {**event, "source": []}, {**event, "cwd": "relative"}):
            with self.subTest(event=invalid):
                code, stdout, stderr = self.invoke(invalid, argv=("session-start",))
                self.assertEqual((code, stderr), (0, ""))
                self.assertIn("unavailable", json.loads(stdout)["hookSpecificOutput"]["additionalContext"])
                self.assertNotIn("/synthetic-private", stdout)
        self.resolve.assert_not_called()

    def test_session_failures_are_informative_without_paths_or_blocking_output(self):
        for error in (Refusal("/synthetic-private/secret"), OSError("/synthetic-private/secret"),
                      TimeoutError(), RuntimeError("/synthetic-private/secret")):
            with self.subTest(error=type(error)):
                self.resolve.side_effect = error
                event = {"hook_event_name": "SessionStart", "source": "resume",
                         "cwd": "/synthetic-checkout"}
                code, stdout, stderr = self.invoke(event, argv=("session-start",))
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(set(json.loads(stdout)), {"hookSpecificOutput"})
                self.assertIn("Read-only", stdout)
                self.assertNotIn("/synthetic-private", stdout)
                self.assertNotIn("permissionDecision", stdout)


class InstalledHookTests(unittest.TestCase):
    def test_native_configuration_limits_lifecycle_and_patch_events(self):
        path = Path(__file__).resolve().parents[1] / ".codex/hooks.json"
        configuration = json.loads(path.read_text())["hooks"]
        self.assertEqual(set(configuration), {"SessionStart", "PreToolUse"})
        startup, = configuration["SessionStart"]
        for source in ("startup", "resume", "clear", "compact", "fork"):
            self.assertIsNotNone(re.fullmatch(startup["matcher"], source))
        self.assertIsNone(re.fullmatch(startup["matcher"], "unrelated"))
        self.assertEqual(startup["hooks"][0]["command"], "graphvon-preflight session-start")
        pretool, = configuration["PreToolUse"]
        self.assertIsNotNone(re.fullmatch(pretool["matcher"], "apply_patch"))
        self.assertIsNone(re.fullmatch(pretool["matcher"], "exec_command"))
        self.assertEqual(pretool["hooks"][0]["command"], "graphvon-preflight")

    def test_linked_worktrees_with_one_common_directory_need_distinct_registration(self):
        with tempfile.TemporaryDirectory(prefix="graphvon-worktree-") as temporary:
            directory = Path(temporary).resolve()
            root, linked = directory / "main", directory / "linked"

            def git(*arguments):
                return subprocess.run(["git", *arguments], check=True, capture_output=True,
                                      text=True).stdout.strip()

            git("init", "--quiet", str(root))
            # An unborn branch supplies a real linked worktree without creating commits.
            git("-C", str(root), "worktree", "add", "--orphan", "-b", "linked", str(linked))
            self.assertEqual(
                git("-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"),
                git("-C", str(linked), "rev-parse", "--path-format=absolute", "--git-common-dir"),
            )
            config = directory / "config/graphvon/config.toml"
            config.parent.mkdir(parents=True)

            def registration(checkout, context):
                return ("[projects." + json.dumps(str(checkout)) + "]\ncontext = "
                        + json.dumps(str(context)) + '\nworking_record = "/synthetic-private/work.md"\n')

            main_context, linked_context = directory / "main.json", directory / "linked.json"
            text = "version = 1\n" + registration(root, main_context)
            config.write_text(text, encoding="utf-8")
            contexts = {main_context: SimpleNamespace(root=root), linked_context: SimpleNamespace(root=linked)}
            environment = {"XDG_CONFIG_HOME": str(config.parent.parent),
                           "PATH": os.environ.get("PATH", os.defpath)}
            with patch.dict(os.environ, environment, clear=True), patch(
                "graphvon.installation.load_context", side_effect=contexts.__getitem__
            ):
                with self.assertRaises(Refusal):
                    resolve_installation(linked, time.monotonic() + 5)
                config.write_text(text + registration(linked, linked_context), encoding="utf-8")
                self.assertEqual(resolve_installation(linked, time.monotonic() + 5).context_path, linked_context)
                self.assertEqual(resolve_installation(root, time.monotonic() + 5).context_path, main_context)


if __name__ == "__main__":
    unittest.main()

"""Adapter checks with controlled readers and patch validation."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from graphvon import hook
from graphvon.contracts import Refusal


class HookTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(
            patch.dict(os.environ, {"GRAPHVON_CONTEXT": "/synthetic-private/context.json"})
        )
        self.clock = self.stack.enter_context(patch.object(hook.time, "monotonic", return_value=100.0))
        self.context = SimpleNamespace(root=Path("/synthetic-checkout"), grants=(), kind="preparation")
        self.load = self.stack.enter_context(patch.object(hook, "load_context", return_value=self.context))
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
        self.load.side_effect = lambda path: calls.append("context") or self.context
        self.checkout.side_effect = lambda *args: calls.append("checkout")
        self.inspect.side_effect = lambda *args: calls.append("patch") or ()
        self.sources.side_effect = lambda *args: calls.append("sources")

        code, stdout, stderr = self.invoke()

        self.assertEqual((code, json.loads(stdout), stderr), (0, {}, ""))
        self.assertEqual(calls, ["context", "checkout", "patch", "sources"])
        self.load.assert_called_once_with(Path("/synthetic-private/context.json"))
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
        self.load.assert_not_called()

    def test_missing_or_relative_locator_has_no_implicit_fallback(self):
        for locator in (None, "", "relative.json"):
            with self.subTest(locator=locator), patch.dict(os.environ, {}, clear=True):
                if locator is not None:
                    os.environ["GRAPHVON_CONTEXT"] = locator
                self.assert_denied(self.invoke())
        self.load.assert_not_called()

    def test_malformed_or_duplicate_json_is_denied(self):
        for raw in (
            "{",
            '{"tool_name":"apply_patch","tool_name":"Bash"}',
            json.dumps({**self.event, "metadata": float("nan")}),
        ):
            with self.subTest(raw=raw):
                self.assert_denied(self.invoke(raw=raw))
        self.load.assert_not_called()

    def test_refused_patch_never_reaches_source_validation(self):
        self.inspect.side_effect = Refusal("A private path must not be echoed: /synthetic-private/context.json")
        self.assert_denied(self.invoke())
        self.sources.assert_not_called()

    def test_failed_source_check_denies_without_exposing_exception_text(self):
        self.sources.side_effect = Refusal("/synthetic-private/context.json contains stale data")
        self.assert_denied(self.invoke())

    def test_context_read_error_is_an_explicit_denial(self):
        self.load.side_effect = OSError("Cannot read /synthetic-private/context.json")
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
        self.load.assert_not_called()
        self.inspect.assert_not_called()

    def test_snapshot_failure_reports_no_basis_or_private_details(self):
        self.observe.side_effect = Refusal("/synthetic-private/context.json")
        code, stdout, stderr = self.invoke(
            argv=("snapshot", "--repository", "example/project", "--issue", "2", "--pull", "4")
        )
        self.assertEqual((code, stdout), (1, ""))
        self.assertNotIn("/synthetic-private", stderr)
        self.assertTrue(stderr)


if __name__ == "__main__":
    unittest.main()

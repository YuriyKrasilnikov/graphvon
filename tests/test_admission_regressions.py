"""Joined admission checks with synthetic GitHub responses and real local Git.

These tests exercise the package's pre-tool decision, not native interception,
patch application, assignment ownership or recovery across a Codex restart.
"""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from graphvon import hook
from graphvon.contracts import Grant, scope_digest
from test_sources import (
    GitHubResponses, PREFIX, REPOSITORY, comment, implementation, observe,
    preparation,
)


DISCUSSION_ENDPOINTS = {
    "issue_comments": PREFIX + "/issues/2/comments?per_page=100",
    "pull_request_issue_comments": PREFIX + "/issues/4/comments?per_page=100",
    "pull_request_reviews": PREFIX + "/pulls/4/reviews?per_page=100",
    "pull_request_review_comments": PREFIX + "/pulls/4/comments?per_page=100",
}
UPDATE = "*** Update File: sample.txt\n@@\n-before\n+after"
MOVE = (
    "*** Update File: move.txt\n*** Move to: moved.txt\n"
    "@@\n-before\n+after"
)


def discussion_record(collection, number):
    row = comment(number)
    if collection == "pull_request_reviews":
        row.update(
            state="COMMENTED", submitted_at="2026-01-01T00:00:00Z",
            commit_id="a" * 40,
        )
    elif collection == "pull_request_review_comments":
        row.update(
            pull_request_review_id=30, path="sample.txt",
            diff_hunk="@@ -1 +1 @@\n-before\n+after",
            commit_id="a" * 40, original_commit_id="a" * 40, line=1,
        )
    return row


def populated_responses():
    responses = GitHubResponses()
    for collection, endpoint in DISCUSSION_ENDPOINTS.items():
        responses.data[endpoint] = [discussion_record(collection, 20)]
    return responses


@unittest.skipUnless(os.name == "posix", "The initial patch profile is POSIX.")
class AdmissionRegressionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="graphvon-admission-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "repo"
        self.root.mkdir()
        self.run_process = subprocess.run
        self.run_process(
            ["git", "init", "--quiet", str(self.root)],
            check=True, capture_output=True,
        )
        self.run_process(
            ["git", "-C", str(self.root), "remote", "add", "origin",
             "https://github.com/" + REPOSITORY + ".git"],
            check=True, capture_output=True,
        )
        for name in ("sample.txt", "move.txt", "protected.txt"):
            (self.root / name).write_text("before\n", encoding="utf-8")
        self.context_path = self.root.parent / "assignment.json"

    def record(self, kind, responses, grants=None):
        if kind == "implementation":
            value = implementation(self.root, observe(responses))
        else:
            value = preparation(self.root)
        if grants is not None:
            value["grants"] = [asdict(grant) for grant in grants]
            scope = scope_digest(kind, value["effect"], grants)
            value["admission"]["scope_sha256"] = scope
            if kind == "implementation":
                value["implementation"]["review"]["scope_sha256"] = scope
        return value

    def files(self):
        return {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(self.root).parts
        }

    def invoke(self, record, responses, *operations):
        # Only external process responses and the event streams are substituted.
        # Context loading, checkout validation, parsing and source joins are real.
        def external_process(arguments, **kwargs):
            if arguments[0] == "gh":
                return responses.run(arguments, **kwargs)
            if arguments[0] == "git":
                return self.run_process(arguments, **kwargs)
            raise AssertionError("Unexpected external process")

        self.context_path.write_text(json.dumps(record), encoding="utf-8")
        retained_context = self.context_path.read_bytes()
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "cwd": str(self.root),
            "tool_input": {
                "command": "*** Begin Patch\n"
                + "\n".join(operations) + "\n*** End Patch"
            },
        }
        before = self.files()
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, {"GRAPHVON_CONTEXT": str(self.context_path)}),
            patch.object(hook.sys, "stdin", io.StringIO(json.dumps(event))),
            patch("graphvon.sources.subprocess.run", side_effect=external_process),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = hook.main([])
        self.assertEqual((code, stderr.getvalue()), (0, ""))
        self.assertEqual(self.files(), before)
        self.assertEqual(self.context_path.read_bytes(), retained_context)
        self.assertNotIn(str(self.context_path), stdout.getvalue())
        return json.loads(stdout.getvalue())

    def assert_allowed(self, result):
        self.assertEqual(result, {})

    def assert_denied(self, result):
        output = result["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "PreToolUse")
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertTrue(output["permissionDecisionReason"])

    def test_current_implementation_allows_with_empty_or_present_discussions(self):
        for responses in (GitHubResponses(), populated_responses()):
            with self.subTest(discussions=bool(responses.data[DISCUSSION_ENDPOINTS["issue_comments"]])):
                record = self.record("implementation", responses)
                self.assert_allowed(self.invoke(record, responses, UPDATE))

    def test_added_edited_or_deleted_discussion_invalidates_current_bodies(self):
        for collection, endpoint in DISCUSSION_ENDPOINTS.items():
            for change in ("add", "edit", "delete"):
                with self.subTest(collection=collection, change=change):
                    original = populated_responses()
                    record = self.record("implementation", original)
                    self.assert_allowed(self.invoke(record, original, UPDATE))
                    current = populated_responses()
                    if change == "add":
                        current.data[endpoint].append(discussion_record(collection, 21))
                    elif change == "edit":
                        # Keep identities and timestamps fixed: content alone matters.
                        current.data[endpoint][0]["body"] = "A changed public decision."
                    else:
                        current.data[endpoint].clear()
                    basis = record["implementation"]["basis"]
                    observed = observe(current)
                    for body in ("issue", "proposal"):
                        self.assertEqual(observed[body], basis[body])
                    self.assertNotEqual(
                        observed["discussions"][collection],
                        basis["discussions"][collection],
                    )
                    self.assert_denied(self.invoke(record, current, UPDATE))
                    self.assert_allowed(self.invoke(record, original, UPDATE))

    def test_branch_head_movement_preserves_current_discussion_admission(self):
        responses = populated_responses()
        record = self.record("implementation", responses)
        responses.data[PREFIX + "/pulls/4"]["head"]["sha"] = "c" * 40
        self.assert_allowed(self.invoke(record, responses, UPDATE))

    def test_preparation_allows_without_implementation_sources(self):
        responses = GitHubResponses()
        record = self.record("preparation", responses)
        self.assertNotIn("implementation", record)
        responses.failures.update(set(responses.data) - {PREFIX})
        self.assert_allowed(self.invoke(record, responses, UPDATE))
        self.assertEqual(set(responses.calls), {PREFIX})

    def test_mixed_patch_refuses_every_order_with_permitted_controls(self):
        undeclared = (
            "*** Add File: undeclared.txt\n+new",
            "*** Update File: protected.txt\n@@\n-before\n+after",
            "*** Delete File: protected.txt",
        )
        for kind in ("implementation", "preparation"):
            responses = GitHubResponses()
            record = self.record(kind, responses)
            for operation in undeclared:
                for operations in ((UPDATE, operation), (operation, UPDATE)):
                    with self.subTest(kind=kind, operations=operations):
                        self.assert_allowed(self.invoke(record, responses, UPDATE))
                        self.assert_denied(self.invoke(record, responses, *operations))
                        self.assert_allowed(self.invoke(record, responses, UPDATE))

    def test_mixed_move_requires_destination_and_preserves_permitted_control(self):
        for kind in ("implementation", "preparation"):
            responses = GitHubResponses()
            grants = [Grant("update", "sample.txt"), Grant("move_from", "move.txt")]
            restricted = self.record(kind, responses, grants)
            complete = self.record(
                kind, responses, grants + [Grant("move_to", "moved.txt")],
            )
            for operations in ((UPDATE, MOVE), (MOVE, UPDATE)):
                with self.subTest(kind=kind, operations=operations):
                    self.assert_allowed(self.invoke(restricted, responses, UPDATE))
                    self.assert_denied(self.invoke(restricted, responses, *operations))
                    self.assert_allowed(self.invoke(complete, responses, *operations))
                    self.assert_denied(self.invoke(restricted, responses, *operations))


if __name__ == "__main__":
    unittest.main()

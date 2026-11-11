"""Core source-contract checks; no network access is needed by this suite."""

from collections import Counter
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from graphvon.contracts import (
    Grant, Refusal, context_from_dict, parse_json, scope_digest,
)
from graphvon.sources import (
    check_checkout, check_source_basis, load_context, observe_basis,
)


REPOSITORY = "example/project"
PREFIX = "repos/" + REPOSITORY
NATIVE_REPOSITORY = {"id": 1, "node_id": "R_example", "full_name": REPOSITORY}
ISSUE = {
    "id": 2, "node_id": "I_requirement", "number": 2, "state": "open",
    "title": "A synthetic requirement", "body": "Keep admitted work possible.",
    "repository_url": "https://api.github.com/repos/" + REPOSITORY,
}
PROPOSAL = {
    "id": 3, "node_id": "PR_proposal", "number": 4, "state": "open", "draft": True,
    "title": "A synthetic proposal", "body": "Check native sources before the edit.",
    "head": {"repo": NATIVE_REPOSITORY, "ref": "feature/example", "sha": "a" * 40},
    "base": {"repo": NATIVE_REPOSITORY, "ref": "main", "sha": "b" * 40},
}


def comment(number):
    return {"id": number, "node_id": f"IC_{number}", "body": f"Synthetic comment {number}",
            "user": {"id": 10, "node_id": "U_example", "login": "example"},
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}


class GitHubResponses:
    """A controlled gh process response, including successive page arrays."""

    def __init__(self):
        self.data = {
            PREFIX: deepcopy(NATIVE_REPOSITORY),
            PREFIX + "/issues/2": deepcopy(ISSUE),
            PREFIX + "/pulls/4": deepcopy(PROPOSAL),
            PREFIX + "/issues/2/comments?per_page=100": [],
            PREFIX + "/issues/4/comments?per_page=100": [],
            PREFIX + "/pulls/4/reviews?per_page=100": [],
            PREFIX + "/pulls/4/comments?per_page=100": [],
        }
        self.pages = {}
        self.failures = set()
        self.raw = {}
        self.change_on_second = None
        self.calls = Counter()
        self.lock = threading.Lock()

    def run(self, arguments, **kwargs):
        if arguments[:2] != ["gh", "api"] or "GET" not in arguments:
            raise AssertionError("Expected a read-only gh API invocation")
        endpoint = next(item for item in arguments if item.startswith("repos/"))
        if "?" in endpoint and "--paginate" not in arguments:
            raise AssertionError("Collection read omitted pagination")
        with self.lock:
            self.calls[endpoint] += 1
            call = self.calls[endpoint]
        payload = deepcopy(self.data[endpoint])
        if call == 2 and self.change_on_second:
            self.change_on_second(endpoint, payload)
        if endpoint in self.failures:
            return subprocess.CompletedProcess(arguments, 1, json.dumps([comment(20)]),
                                               "later page failed; /synthetic/private/record.json")
        if endpoint in self.raw:
            text = self.raw[endpoint]
        elif endpoint in self.pages:
            text = "\n".join(json.dumps(page) for page in self.pages[endpoint])
        else:
            text = json.dumps(payload)
        return subprocess.CompletedProcess(arguments, 0, text, "")


def preparation(root):
    grants = [Grant("update", "sample.txt")]
    kind, effect = "preparation", "Prepare an already admitted proposal"
    return {"version": 1, "kind": kind, "root": str(root),
            "repository": {"name": REPOSITORY, "id": "R_example", "remote": "origin"},
            "owner": "coordinator", "generation": "synthetic-generation", "effect": effect,
            "grants": [asdict(grant) for grant in grants],
            "admission": {"reference": "owner-instruction:synthetic", "sha256": "0" * 64,
                          "scope_sha256": scope_digest(kind, effect, grants)}}


def implementation(root, basis):
    value = preparation(root)
    value["kind"] = "implementation"
    value["effect"] = "Implement the reviewed synthetic change"
    scope = scope_digest(value["kind"], value["effect"], [Grant(**item) for item in value["grants"]])
    value["admission"]["scope_sha256"] = scope
    value["implementation"] = {
        "issue_number": 2, "pull_number": 4, "basis": basis,
        "review": {"reference": "review-evidence:synthetic", "sha256": "1" * 64,
                   "requirement_sha256": basis["issue"]["content_sha256"],
                   "proposal_sha256": basis["proposal"]["content_sha256"], "scope_sha256": scope,
                   "provenance": "Separate synthetic reviewer", "conclusion": "proceed", "limits": []},
    }
    return value


def observe(fake):
    with patch("graphvon.sources.subprocess.run", side_effect=fake.run):
        return observe_basis(REPOSITORY, 2, 4, time.monotonic() + 10)


class ContractTests(unittest.TestCase):
    def test_preparation_is_immutable_and_has_no_implementation_prerequisite(self):
        context = context_from_dict(preparation(Path("/synthetic/checkout")))
        self.assertIsNone(context.implementation)
        self.assertEqual(context.grants, (Grant("update", "sample.txt"),))
        with self.assertRaises(FrozenInstanceError):
            context.owner = "changed"
        with patch("graphvon.sources.subprocess.run") as run:
            check_source_basis(context, time.monotonic() + 1)
        run.assert_not_called()

    def test_changed_scope_and_extra_approval_field_refuse(self):
        value = preparation(Path("/synthetic/checkout"))
        value["grants"][0]["path"] = "another.txt"
        with self.assertRaises(Refusal):
            context_from_dict(value)
        value = preparation(Path("/synthetic/checkout"))
        value["approved"] = True
        with self.assertRaises(Refusal):
            context_from_dict(value)

    def test_scope_digest_is_independent_of_grant_order(self):
        grants = [Grant("add", "one.txt"), Grant("update", "two.txt")]
        self.assertEqual(scope_digest("preparation", "Synthetic effect", grants),
                         scope_digest("preparation", "Synthetic effect", grants[::-1]))

    def test_invalid_grants_and_contradictory_variants_refuse(self):
        for arguments in [("execute", "a"), ("add", "../a"), ("update", "/a"),
                          ("mkdir", "a", True), ("update", "a", "false")]:
            with self.subTest(arguments=arguments), self.assertRaises(Refusal):
                Grant(*arguments)
        value = preparation(Path("/synthetic/checkout"))
        value["implementation"] = None
        with self.assertRaises(Refusal):
            context_from_dict(value)

    def test_valid_implementation_and_mismatched_review_basis(self):
        basis = observe(GitHubResponses())
        value = implementation(Path("/synthetic/checkout"), basis)
        context = context_from_dict(value)
        self.assertEqual(context.implementation.basis.to_dict(), basis)
        value["implementation"]["review"]["proposal_sha256"] = "f" * 64
        with self.assertRaises(Refusal):
            context_from_dict(value)

    def test_duplicate_fields_and_nonfinite_json_refuse(self):
        for text in ['{"kind":"preparation","kind":"implementation"}', '{"value":NaN}']:
            with self.subTest(text=text), self.assertRaises(Refusal):
                parse_json(text)

    def test_context_locator_is_explicit_and_errors_are_redacted(self):
        with tempfile.TemporaryDirectory(prefix="graphvon-context-test-") as directory:
            root = Path(directory)
            locator = root / "synthetic-context.json"
            locator.write_text(json.dumps(preparation(root)))
            self.assertEqual(load_context(locator).root, root)
            locator.unlink()
            with self.assertRaises(Refusal) as caught:
                load_context(locator)
            self.assertNotIn(str(locator), str(caught.exception))
        with self.assertRaises(Refusal):
            load_context("synthetic-context.json")

    def test_context_descriptors_close_after_success_and_refusal(self):
        with tempfile.TemporaryDirectory(prefix="graphvon-context-read-") as directory:
            root = Path(directory)
            locator = root / "synthetic-context.json"
            real_open = os.open
            acquired = []

            def observe_open(*arguments, **keywords):
                descriptor = real_open(*arguments, **keywords)
                acquired.append(descriptor)
                return descriptor

            with patch("graphvon.sources.os.open", side_effect=observe_open):
                locator.write_text(json.dumps(preparation(root)))
                self.assertEqual(load_context(locator).root, root)
                locator.write_text("{")
                with self.assertRaises(Refusal):
                    load_context(locator)
                with self.assertRaises(Refusal):
                    load_context(root)
            self.assertEqual(len(acquired), 3)
            for descriptor in acquired:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    @unittest.skipUnless(os.name == "posix", "The supported profile uses POSIX descriptors")
    def test_adapter_denies_fifo_and_directory_context_within_budget(self):
        from graphvon.hook import READ_BUDGET_SECONDS

        with tempfile.TemporaryDirectory(prefix="graphvon-context-read-") as directory:
            root = Path(directory)
            fifo = root / "synthetic-context.fifo"
            os.mkfifo(fifo)
            event = {"hook_event_name": "PreToolUse", "tool_name": "apply_patch", "cwd": str(root),
                     "tool_input": {"command": "*** Begin Patch\n*** Add File: sample.txt\n+synthetic\n*** End Patch\n"}}
            for locator in (fifo, root):
                with self.subTest(kind="fifo" if locator == fifo else "directory"):
                    environment = os.environ.copy()
                    environment["GRAPHVON_CONTEXT"] = str(locator)
                    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
                    environment["PYTHONDONTWRITEBYTECODE"] = "1"
                    started = time.monotonic()
                    completed = subprocess.run([sys.executable, "-m", "graphvon.hook"],
                                               input=json.dumps(event), text=True, capture_output=True,
                                               cwd=root, env=environment, timeout=READ_BUDGET_SECONDS)
                    self.assertLess(time.monotonic() - started, READ_BUDGET_SECONDS)
                    self.assertEqual(completed.returncode, 0)
                    output = json.loads(completed.stdout)["hookSpecificOutput"]
                    self.assertEqual(output["permissionDecision"], "deny")
                    self.assertIn("context", output["permissionDecisionReason"])
                    self.assertNotIn(str(locator), completed.stdout + completed.stderr)
                    self.assertFalse((root / "sample.txt").exists())


class ReadbackTests(unittest.TestCase):
    def test_all_pages_are_retained_in_both_complete_observations(self):
        for combined in (True, False):
            with self.subTest(combined_output=combined):
                fake = GitHubResponses()
                endpoint = PREFIX + "/issues/2/comments?per_page=100"
                if combined:
                    fake.data[endpoint] = [comment(20), comment(21)]
                else:
                    fake.pages[endpoint] = [[comment(20)], [comment(21)]]
                basis = observe(fake)
                self.assertTrue(basis["complete"])
                self.assertEqual([item["id"] for item in basis["discussions"]["issue_comments"]], ["IC_20", "IC_21"])
                self.assertEqual(set(fake.calls.values()), {2})

    def test_later_page_failure_refuses_partial_output_and_redacts_stderr(self):
        fake = GitHubResponses()
        fake.failures.add(PREFIX + "/issues/2/comments?per_page=100")
        with self.assertRaises(Refusal) as caught:
            observe(fake)
        self.assertNotIn("/synthetic/private/record.json", str(caught.exception))

    def test_duplicate_identity_or_malformed_second_page_refuses(self):
        endpoint = PREFIX + "/issues/2/comments?per_page=100"
        for text in [json.dumps([comment(20)]) + json.dumps([comment(20)]), "[]\n{", "[]\n{}"]:
            fake = GitHubResponses()
            fake.raw[endpoint] = text
            with self.subTest(text=text), self.assertRaises(Refusal):
                observe(fake)

    def test_missing_native_identity_and_wrong_number_refuse(self):
        fake = GitHubResponses()
        del fake.data[PREFIX + "/issues/2"]["node_id"]
        with self.assertRaises(Refusal):
            observe(fake)
        fake = GitHubResponses()
        fake.data[PREFIX + "/pulls/4"]["number"] = 5
        with self.assertRaises(Refusal):
            observe(fake)

    def test_branch_commit_churn_does_not_change_design_basis(self):
        fake = GitHubResponses()
        def move_head(endpoint, payload):
            if endpoint == PREFIX + "/pulls/4":
                payload["head"]["sha"] = "c" * 40
        fake.change_on_second = move_head
        self.assertEqual(observe(fake), observe(GitHubResponses()))

    def test_changed_requirement_between_passes_refuses(self):
        fake = GitHubResponses()
        def change_requirement(endpoint, payload):
            if endpoint == PREFIX + "/issues/2":
                payload["body"] += " Additional requirement."
        fake.change_on_second = change_requirement
        with self.assertRaises(Refusal):
            observe(fake)

    def test_current_basis_must_match_admitted_basis(self):
        value = implementation(Path("/synthetic/checkout"), observe(GitHubResponses()))
        context = context_from_dict(value)
        fake = GitHubResponses()
        with patch("graphvon.sources.subprocess.run", side_effect=fake.run):
            check_source_basis(context, time.monotonic() + 10)
        fake = GitHubResponses()
        fake.data[PREFIX + "/issues/2"]["body"] = "Changed requirement."
        with patch("graphvon.sources.subprocess.run", side_effect=fake.run), self.assertRaises(Refusal):
            check_source_basis(context, time.monotonic() + 10)

    def test_expired_deadline_starts_no_subprocess(self):
        with patch("graphvon.sources.subprocess.run") as run, self.assertRaises(Refusal):
            observe_basis(REPOSITORY, 2, 4, time.monotonic() - 1)
        run.assert_not_called()


class CheckoutTests(unittest.TestCase):
    def test_actual_checkout_remote_and_native_identity_are_checked(self):
        with tempfile.TemporaryDirectory(prefix="graphvon-checkout-test-") as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root), "remote", "add", "origin", "https://github.com/example/project.git"], check=True)
            context = context_from_dict(preparation(root))
            with patch("graphvon.sources._read", return_value=NATIVE_REPOSITORY) as read:
                check_checkout(context, root, time.monotonic() + 5)
                read.assert_called_once()
            wrong_identity = {**NATIVE_REPOSITORY, "node_id": "R_recreated"}
            with patch("graphvon.sources._read", return_value=wrong_identity), self.assertRaises(Refusal):
                check_checkout(context, root, time.monotonic() + 5)
            subprocess.run(["git", "-C", str(root), "remote", "set-url", "origin", "https://github.com/example/other.git"], check=True)
            with patch("graphvon.sources._read") as read, self.assertRaises(Refusal):
                check_checkout(context, root, time.monotonic() + 5)
            read.assert_not_called()
            child = root / "child"
            child.mkdir()
            child_context = context_from_dict(preparation(child))
            with self.assertRaises(Refusal):
                check_checkout(child_context, child, time.monotonic() + 5)


if __name__ == "__main__":
    unittest.main()

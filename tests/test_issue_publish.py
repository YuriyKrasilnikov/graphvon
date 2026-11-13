"""Publication protocol tests using controlled local records and native transport."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from graphvon.contracts import Refusal
from graphvon.issue_publish import Native, create, reconcile
from graphvon.issue_records import save_record
from test_issue_check import make_project, make_proposal


SUBJECT = "a" * 64
PARENT = {"number": 2, "id": 100, "node_id": "I_parent"}
CHILD = {"number": 3, "id": 101, "node_id": "I_child"}


class Transport:
    def __init__(self, repository):
        self.repository = repository
        self.posts = []
        self.response = {"kind": "response", "value": self.issue(CHILD, "Export", "Body\n")}
        self.fail_parent = False

    def issue(self, ident, title="parent", body=""):
        return {**ident, "title": title, "body": body,
                "repository_url": "https://api.github.com/repos/" + self.repository}

    def get(self, path):
        if path.endswith("/parent"):
            if self.fail_parent:
                raise Refusal("unavailable")
            return self.issue(PARENT)
        if path.endswith("/issues/2"):
            return self.issue(PARENT)
        return self.issue(CHILD, "Export", "Body\n")

    def post(self, payload):
        self.posts.append(deepcopy(payload))
        return deepcopy(self.response)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = make_project(self.root)
        self.project_path = self.root / "project.json"
        self.record_path = self.root / "proposal.json"
        self.project_path.write_text(json.dumps(self.project))
        self.record = make_proposal()
        self.record["candidate"]["native_parent"] = PARENT
        self.record_path.write_text(json.dumps(self.record))
        self.transport = Transport("example/project")
        self.factory = lambda repository: self.transport
        self.request = {"version": 1, "project_basis": str(self.project_path), "proposal": str(self.record_path),
                        "expected_record_revision": "1", "authorization": {"source": "owner permission",
                        "subject_sha256": SUBJECT, "effect": "create_issue"}}
        self.report = {"structure": {"status": "valid"}, "source_coverage": {"status": "consistent_with_assessed_basis"},
                       "semantic_assessment": {"applicability": "matches_subject", "declared_results":
                       {"preservation": "supported", "readiness": "supported", "publication": "supported", "definition": "unknown"},
                       "judgment_context": {"readiness_action": "create_issue"}}, "subject_sha256": SUBJECT,
                       "public_payload": {"title": "Export", "body": "Body\n"}}
        self.checker = patch("graphvon.issue_publish.check", return_value=self.report)
        self.checker.start()

    def tearDown(self):
        self.checker.stop()
        self.tmp.cleanup()

    def test_creation_requires_bound_judgments_and_allowlists_native_payload(self):
        result = create(self.request, self.factory)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(self.transport.posts, [{"title": "Export", "body": "Body\n", "parent_issue_id": 100}])
        stored = json.loads(self.record_path.read_text())
        self.assertEqual(stored["operation"]["state"], "confirmed")
        self.assertEqual(stored["operation"]["observations"][-1]["parent"]["identity"], PARENT)

    def test_stale_sources_or_permission_cannot_send(self):
        self.report["source_coverage"]["status"] = "partial"
        with self.assertRaises(Refusal):
            create(self.request, self.factory)
        self.assertEqual(self.transport.posts, [])
        self.report["source_coverage"]["status"] = "consistent_with_assessed_basis"
        self.request["authorization"]["subject_sha256"] = "b" * 64
        with self.assertRaises(Refusal):
            create(self.request, self.factory)
        self.assertEqual(self.transport.posts, [])

    def test_post_uses_one_versioned_json_request_and_keeps_rejection_distinct(self):
        payload = {"title": "Example", "body": "Text", "parent_issue_id": 42}
        native = Native("example/project")
        response = SimpleNamespace(returncode=1, stdout="HTTP/2 422 Unprocessable Entity\r\n\r\n{}", stderr="")
        with patch("graphvon.issue_publish.subprocess.run", return_value=response) as run:
            self.assertEqual(native.post(payload), {"kind": "rejected", "status": 422})
        command = run.call_args.args[0]
        self.assertIn("2026-03-10", " ".join(command))
        self.assertEqual(command.count("POST"), 1)
        self.assertEqual(json.loads(run.call_args.kwargs["input"]), payload)
        response.stdout = "HTTP/2 500 Internal Server Error\r\n\r\n{}"
        with patch("graphvon.issue_publish.subprocess.run", return_value=response):
            self.assertEqual(native.post(payload), {"kind": "unknown"})

    def test_unknown_send_cannot_retry_and_reconcile_uses_get_only(self):
        self.transport.response = {"kind": "unknown"}
        result = create(self.request, self.factory)
        self.assertEqual(result["status"], "sending")
        again = {**self.request, "expected_record_revision": result["record_revision"], "owner_settled": True}
        with self.assertRaises(Refusal):
            create(again, self.factory)
        recovered = reconcile({"version": 1, "proposal": str(self.record_path),
                               "expected_record_revision": result["record_revision"], "candidate": CHILD,
                               "resolution_evidence": "Owner attributed the native response"}, self.factory)
        self.assertEqual(recovered["status"], "confirmed")
        self.assertEqual(len(self.transport.posts), 1)

    def test_parent_readback_failure_retains_known_object(self):
        self.transport.fail_parent = True
        result = create(self.request, self.factory)
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["observation"]["object"]["identity"], CHILD)
        self.assertIn("parent_unavailable", result["observation"]["discrepancies"])

    def test_persistence_failure_before_sending_holds_post(self):
        with patch("graphvon.issue_publish.save_record", side_effect=Refusal("failure")):
            with self.assertRaises(Refusal):
                create(self.request, self.factory)
        self.assertEqual(self.transport.posts, [])

    def test_unambiguous_rejection_is_retained_without_retry(self):
        self.transport.response = {"kind": "rejected", "status": 422}
        result = create(self.request, self.factory)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["observation"]["rejection_status"], 422)
        with self.assertRaises(Refusal):
            create({**self.request, "expected_record_revision": result["record_revision"]}, self.factory)
        self.assertEqual(len(self.transport.posts), 1)
        self.transport.response = {"kind": "response", "value": self.transport.issue(CHILD, "Export", "Body\n")}
        retry = {**self.request, "expected_record_revision": result["record_revision"], "owner_settled": True,
                 "rejection_resolution": "The cause and current permission were assessed"}
        completed = create(retry, self.factory)
        self.assertEqual(completed["status"], "confirmed")
        prior = json.loads(self.record_path.read_text())["operation"]["prior_rejections"]
        self.assertEqual(prior[0]["operation"]["state"], "rejected")
        self.assertNotEqual(prior[0]["operation"]["id"], completed["operation_id"])

    def test_prepared_continuation_needs_settled_owner_and_same_permission(self):
        calls = 0

        def interrupted(path, record):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise Refusal("interrupted before sending persistence")
            return save_record(path, record)

        with patch("graphvon.issue_publish.save_record", side_effect=interrupted):
            with self.assertRaises(Refusal):
                create(self.request, self.factory)
        stored = json.loads(self.record_path.read_text())
        self.assertEqual(stored["operation"]["state"], "prepared")
        self.assertEqual(self.transport.posts, [])
        continuation = {**self.request, "expected_record_revision": stored["record_revision"]}
        with self.assertRaises(Refusal):
            create(continuation, self.factory)
        continuation["owner_settled"] = True
        result = create(continuation, self.factory)
        self.assertEqual(result["operation_id"], stored["operation"]["id"])
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(len(self.transport.posts), 1)

    def test_failed_result_persistence_retains_returned_identity(self):
        calls = 0

        def failed_result(path, record):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise Refusal("result unavailable")
            return save_record(path, record)

        with patch("graphvon.issue_publish.save_record", side_effect=failed_result):
            result = create(self.request, self.factory)
        self.assertEqual(result["persistence"], "unknown")
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["observation"]["object"]["identity"], CHILD)
        self.assertEqual(json.loads(self.record_path.read_text())["operation"]["state"], "observed")

    def test_response_identity_survives_interruption_before_readback(self):
        original_get = self.transport.get

        def interrupted(path):
            if path.endswith("/issues/3"):
                raise KeyboardInterrupt()
            return original_get(path)

        self.transport.get = interrupted
        with self.assertRaises(KeyboardInterrupt):
            create(self.request, self.factory)
        stored = json.loads(self.record_path.read_text())
        self.assertEqual(stored["operation"]["state"], "observed")
        self.assertEqual(stored["operation"]["observations"][-1]["candidate"], CHILD)
        stored["candidate"]["native_parent"] = {"number": 4, "id": 102, "node_id": "I_new_parent"}
        self.record_path.write_text(json.dumps(stored))
        self.transport.get = original_get
        result = reconcile({"version": 1, "proposal": str(self.record_path),
                            "expected_record_revision": stored["record_revision"]}, self.factory)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["observation"]["parent"]["identity"], PARENT)
        self.assertEqual(len(self.transport.posts), 1)

    def test_failed_identity_checkpoint_returns_identity_without_readback(self):
        calls = 0

        def fail_checkpoint(path, record):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise Refusal("checkpoint failed")
            return save_record(path, record)

        original_get = self.transport.get
        reads = []

        def record_get(path):
            reads.append(path)
            return original_get(path)

        self.transport.get = record_get
        with patch("graphvon.issue_publish.save_record", side_effect=fail_checkpoint):
            result = create(self.request, self.factory)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["persistence"], "unknown")
        self.assertEqual(result["observation"]["candidate"], CHILD)
        self.assertFalse(any(path.endswith("/issues/3") for path in reads))
        self.assertEqual(json.loads(self.record_path.read_text())["operation"]["state"], "sending")

    def test_new_assessed_parent_after_rejection_preserves_prior_intent(self):
        self.transport.response = {"kind": "rejected", "status": 422}
        result = create(self.request, self.factory)
        stored = json.loads(self.record_path.read_text())
        new_parent = {"number": 4, "id": 102, "node_id": "I_new_parent"}
        stored["candidate"]["native_parent"] = new_parent
        self.record_path.write_text(json.dumps(stored))
        original_get = self.transport.get

        def read_new_parent(path):
            if path.endswith("/issues/4") or path.endswith("/parent"):
                return self.transport.issue(new_parent)
            return original_get(path)

        self.transport.get = read_new_parent
        self.transport.response = {"kind": "response", "value": self.transport.issue(CHILD, "Export", "Body\n")}
        self.report["subject_sha256"] = "b" * 64
        retry = {**self.request, "expected_record_revision": result["record_revision"], "owner_settled": True,
                 "authorization": {**self.request["authorization"], "subject_sha256": "b" * 64},
                 "rejection_resolution": "New parent and permission assessed"}
        completed = create(retry, self.factory)
        self.assertEqual(completed["status"], "confirmed")
        operation = json.loads(self.record_path.read_text())["operation"]
        self.assertEqual(operation["parent"], new_parent)
        prior = operation["prior_rejections"][0]["operation"]
        self.assertEqual(prior["parent"], PARENT)
        self.assertEqual(prior["payload"]["parent_issue_id"], PARENT["id"])

    def test_prepared_operation_refuses_changed_parent(self):
        calls = 0

        def interrupted(path, record):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise Refusal("interrupted")
            return save_record(path, record)

        with patch("graphvon.issue_publish.save_record", side_effect=interrupted):
            with self.assertRaises(Refusal):
                create(self.request, self.factory)
        stored = json.loads(self.record_path.read_text())
        stored["candidate"]["native_parent"] = {**PARENT, "node_id": "I_different"}
        self.record_path.write_text(json.dumps(stored))
        self.transport.get = lambda path: self.transport.issue(stored["candidate"]["native_parent"])
        with self.assertRaises(Refusal):
            create({**self.request, "expected_record_revision": stored["record_revision"], "owner_settled": True}, self.factory)
        self.assertEqual(self.transport.posts, [])

    def test_changed_native_parent_blocks_send(self):
        self.record["candidate"]["native_parent"] = {**PARENT, "id": 999}
        self.record_path.write_text(json.dumps(self.record))
        with self.assertRaises(Refusal):
            create(self.request, self.factory)
        self.assertEqual(self.transport.posts, [])

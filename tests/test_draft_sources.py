"""Native observation uses only GET and requires two matching complete passes."""

import unittest
from types import SimpleNamespace

from graphvon.contracts import Refusal
from graphvon.draft_sources import action_context, observe


class Reader:
    project = SimpleNamespace(repository="example/project", repository_id="R_repo")

    def __init__(self):
        self.calls = []
        self.changed = False

    def _get(self, endpoint, *, paginated=False):
        self.calls.append((endpoint, paginated))
        if endpoint == "repos/example/project": return {"id": 10, "node_id": "R_repo", "full_name": "example/project"}
        if "comments?" in endpoint or "reviews?" in endpoint: return []
        if endpoint.endswith("/issues/1"):
            return {"id": 11, "number": 1, "node_id": "I_one", "title": "Goal", "body": "Changed" if self.changed and self.calls.count((endpoint, False)) > 1 else "Body", "state": "open", "repository_url": "https://api.github.com/repos/example/project"}
        if endpoint.endswith("/pulls/2"):
            branch = {"repo": {"node_id": "R_repo"}, "ref": "main", "sha": "a" * 40}
            return {"id": 12, "number": 2, "node_id": "PR_two", "title": "Plan", "body": "Body", "state": "open", "draft": True, "head": branch, "base": branch}
        raise AssertionError(endpoint)


class NativeObservationTests(unittest.TestCase):
    def test_candidate_without_pr_performs_no_pr_reads(self):
        reader = Reader()
        result = observe(reader, {"number": 1, "node_id": "I_one"}, None)
        self.assertEqual(result["status"], "stable")
        self.assertIsNone(result["observation"]["pr"])
        self.assertFalse(any("/pulls/" in path for path, _ in reader.calls))

    def test_changed_observations_are_not_treated_as_stable(self):
        reader = Reader(); reader.changed = True
        with self.assertRaises(Refusal): observe(reader, {"number": 1, "node_id": "I_one"}, None)

    def test_existing_pr_reads_all_discussion_collections(self):
        reader = Reader()
        result = observe(reader, {"number": 1, "node_id": "I_one"}, {"number": 2, "node_id": "PR_two"})
        self.assertTrue(result["observation"]["pr"]["draft"])
        self.assertEqual(len([x for x in reader.calls if x[1]]), 8)

    def test_action_context_preserves_envelopes_and_ignores_fetch_bookkeeping(self):
        reader = Reader()
        result = observe(reader, {"number": 1, "node_id": "I_one"}, {"number": 2, "node_id": "PR_two"})
        envelope = {"id": "review", "updated_at": None, "submitted_at": "2026-11-13T00:00:00Z", "content_sha256": "b" * 64}
        result["observation"]["discussions"]["pull_request_reviews"] = [envelope]
        first = action_context(result)
        result["fetch_timestamp"] = "not semantic"
        second = action_context(result)
        self.assertEqual(first, second)
        self.assertEqual(first["discussions"]["pull_request_reviews"], [envelope])
        self.assertEqual(set(first["discussions"]), {"issue_comments", "pull_request_issue_comments", "pull_request_reviews", "pull_request_review_comments"})

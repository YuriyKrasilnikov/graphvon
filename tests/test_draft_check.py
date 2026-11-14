"""Report propagation cases with supplied fixture judgments, not a semantic oracle."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from graphvon.contracts import Refusal, canonical_json
from graphvon.draft_check import check
from graphvon.draft_contracts import action_context_subject, subjects
from graphvon.draft_sources import action_context
from graphvon.issue_check import SourceReader
from graphvon.issue_contracts import text_digest
from test_issue_check import make_project


NATIVE = canonical_json({"id": "I_one", "title": "Goal", "body": "## Goal\nBuild it.\n", "comments": []})
J = {"result": "supported", "reasons": ["Independent fixture judgment"]}


class LocalReader(SourceReader):
    def prepare(self): pass
    def read(self, source):
        return NATIVE if source.kind == "github_issue" else super().read(source)


def native(reader, issue, pr):
    return {"status": "stable", "coverage": "two complete passes", "observation": {"repository": {"name": "example/project", "id": "R_example"},
        "issue": {"number": 1, "node_id": "I_one", "state": "open", "title": "Goal", "body": "## Goal\nBuild it.\n"}, "issue_comments": [], "pr": None, "discussions": {}}}


def native_pr(reader, issue, pr):
    result = native(reader, issue, pr)
    branch = {"repository_id": "R_example", "ref": "main", "sha": "a" * 40}
    result["observation"]["pr"] = {"number": 2, "node_id": "PR_two", "title": "Plan", "body": "## Plan\nBuild it.\n", "state": "open", "draft": True, "head": branch, "base": deepcopy(branch)}
    result["observation"]["discussions"] = {"pull_request_issue_comments": [], "pull_request_reviews": [], "pull_request_review_comments": []}
    return result


def bind_receipt(project, issue, draft, observed, judgment=J):
    basis = action_context(observed)
    ids = subjects(project, issue, draft)
    return {"subject_sha256": action_context_subject(draft["trace"]["action"], draft["assessment"]["scope"], ids, basis),
            "basis": basis, "provenance": "Independent fixture context assessment", "scope": draft["assessment"]["scope"],
            "applicability": deepcopy(judgment), "limits": []}


def fixture(root):
    project = make_project(root)
    template = "## Plan\n<!-- Write the plan. -->\n"
    (root / "change.yml").write_text(template)
    project["sources"][1]["sha256"] = text_digest(template)
    project["profiles"] = [{"template": "form", "sections": [{"heading": "Plan", "required": True,
                             "rule_refs": [{"source": "project:rules", "selector": {"kind": "whole", "target": "source_text"}}]}]}]
    project["assessment"]["subject_sha256"] = "0" * 64
    issue = {"schema_version": 1, "artifact_id": "goal", "record_revision": "one",
             "repository": project["repository"], "issue": {"number": 1, "node_id": "I_one", "source": "goal"},
             "scope": "upstream scope", "sources": [{"key": "goal", "kind": "github_issue", "location": 1,
             "sha256": text_digest(NATIVE), "applicability": "required", "basis": "fixture", "owner": "owner", "status": "current"}],
             "conditions": [], "obligations": [{"id": "goal", "statement": "Build it", "source_refs": [], "condition_ids": [], "acceptance": "Works"}],
             "shared_constraints": [], "remaining": [], "unknowns": [], "assessment": None}
    action = {"kind": "discuss", "description": "Discuss this plan"}
    draft = {"schema_version": 1, "artifact_id": "plan", "record_revision": "one",
             "candidate": {"template": "form", "title": "Plan", "body": "## Plan\nBuild it.\n", "issue": {"number": 1, "node_id": "I_one"}, "native_pr": None},
             "trace": {"scope": "different draft scope", "action": action, "source_keys": ["rules", "form", "goal"],
                       "conditions": [], "unknowns": [], "remaining": [], "obligations": [{"issue_obligation": "goal", "coverage": "covered",
                       "plan_refs": [{"heading": "Plan", "start": 8, "end": 17, "text": "Build it."}], "verification": "Check", "remainder": ""}],
                       "effects": [], "constraints": []}, "assessment": None}
    ids = subjects(project, issue, draft)
    project["assessment"]["subject_sha256"] = ids["project"]
    issue["assessment"] = {"subject_sha256": ids["issue"], "provenance": "Independent fixture", "scope": issue["scope"],
                           "preservation": deepcopy(J), "publication": deepcopy(J), "actions": [{"action": action, "definition": deepcopy(J), "adequacy": deepcopy(J)}], "limits": [], "supersedes": None}
    ids = subjects(project, issue, draft)
    draft["assessment"] = {"local_subject_sha256": ids["local"], "composition_subject_sha256": ids["composition"], "provenance": "Independent fixture", "scope": draft["trace"]["scope"],
                           "local_preservation": deepcopy(J), "justification": deepcopy(J), "definition": deepcopy(J), "joint_constraints": deepcopy(J), "publication": deepcopy(J),
                           "readiness": {"action": action, **deepcopy(J)}, "limits": []}
    return project, issue, draft


class DraftReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.project, self.issue, self.draft = fixture(self.root)

    def tearDown(self): self.temp.cleanup()

    def report(self):
        from graphvon.draft_contracts import parse_draft_project
        reader = LocalReader(parse_draft_project(self.project), "working")
        return check(self.project, self.issue, self.draft, "working", reader, native)

    def implementation_fixture(self):
        action = {"kind": "implement", "description": "Implement the plan"}
        self.draft["trace"]["action"] = action
        self.draft["candidate"]["native_pr"] = {"number": 2, "node_id": "PR_two"}
        self.issue["assessment"]["actions"][0]["action"] = action
        ids = subjects(self.project, self.issue, self.draft)
        self.draft["assessment"]["local_subject_sha256"] = ids["local"]
        self.draft["assessment"]["composition_subject_sha256"] = ids["composition"]
        self.draft["assessment"]["readiness"]["action"] = action
        observed = native_pr(None, None, None)
        self.draft["assessment"]["readiness"]["native_context"] = bind_receipt(self.project, self.issue, self.draft, observed)
        return observed

    def report_with_native(self, observed):
        from graphvon.draft_contracts import parse_draft_project
        reader = LocalReader(parse_draft_project(self.project), "working")
        return check(self.project, self.issue, self.draft, "working", reader, lambda *_: deepcopy(observed))

    def test_applicable_distinct_scopes_do_not_imply_conflict(self):
        result = self.report()
        self.assertEqual(result["structure"]["status"], "valid")
        self.assertEqual(result["composition"]["status"], "supported_by_applicable_assessment")
        self.assertEqual(result["next_action"]["status"], "supported_by_applicable_assessment")

    def test_changed_upstream_assessment_stales_composition_not_local(self):
        self.issue["assessment"]["limits"] = ["Changed condition"]
        result = self.report()
        self.assertEqual(result["local_correspondence"]["status"], "supported_by_applicable_assessment")
        self.assertEqual(result["composition"]["status"], "unknown")

    def test_explicit_joint_discrepancy_and_missing_profile_source_remain_visible(self):
        self.draft["assessment"]["joint_constraints"] = {"result": "discrepancy", "reasons": ["Conflicting conditions"]}
        result = self.report()
        self.assertEqual(result["composition"]["status"], "discrepancy_reported")
        (self.root / "private-source.txt").unlink()
        result = self.report()
        self.assertEqual(result["composition"]["status"], "unknown")
        self.assertIn("source_unavailable", result["source_coverage"]["findings"])

    def test_filled_heading_does_not_establish_semantic_support(self):
        self.draft["assessment"] = None
        result = self.report()
        self.assertEqual(result["structure"]["status"], "valid")
        self.assertEqual(result["local_correspondence"]["status"], "not_assessed")

    def test_applicable_local_discrepancy_is_retained_alongside_unavailable_dependency(self):
        source = {"key": "governing", "kind": "local_file", "location": str(self.root / "missing"),
                  "sha256": "0" * 64, "applicability": "required", "basis": "fixture",
                  "owner": "owner", "status": "current"}
        self.issue["sources"].append(source)
        self.issue["assessment"]["subject_sha256"] = subjects(self.project, self.issue, self.draft)["issue"]
        ids = subjects(self.project, self.issue, self.draft)
        self.draft["assessment"]["composition_subject_sha256"] = ids["composition"]
        self.draft["assessment"]["local_preservation"] = {"result": "discrepancy", "reasons": ["Omitted outcome"]}
        result = self.report()
        self.assertEqual(result["composition"]["status"], "discrepancy_reported")
        self.assertIn("source_unavailable", result["source_coverage"]["findings"])

    def test_changed_governing_source_does_not_erase_local_correspondence(self):
        path = self.root / "dependency"
        path.write_text("before")
        self.issue["sources"].append({"key": "governing", "kind": "local_file", "location": str(path),
                                      "sha256": text_digest("before"), "applicability": "required", "basis": "fixture",
                                      "owner": "owner", "status": "current"})
        self.issue["obligations"][0]["source_refs"] = [{"source": "issue:governing", "selector": {"kind": "whole", "target": "source_text"}}]
        self.issue["assessment"]["subject_sha256"] = subjects(self.project, self.issue, self.draft)["issue"]
        ids = subjects(self.project, self.issue, self.draft)
        self.draft["assessment"]["local_subject_sha256"] = ids["local"]
        self.draft["assessment"]["composition_subject_sha256"] = ids["composition"]
        path.write_text("after")
        result = self.report()
        self.assertEqual(result["local_correspondence"]["status"], "supported_by_applicable_assessment")
        self.assertEqual(result["composition"]["status"], "unknown")
        self.assertEqual(result["assessments"]["issue"]["applicability"], "stale")

    def test_invalid_draft_local_effect_source_holds_local_correspondence(self):
        for ref in [
            {"source": "issue:missing", "selector": {"kind": "whole", "target": "source_text"}},
            {"source": "issue:goal", "selector": {"kind": "exact", "target": "issue_body", "start": 0, "end": 2, "text": "no"}},
        ]:
            with self.subTest(ref=ref):
                self.draft["trace"]["effects"] = [{"id": "derived", "plan_refs": [], "kind": "derived_obligation",
                    "issue_obligations": ["goal"], "source_refs": [ref], "rationale": "Fixture rationale"}]
                ids = subjects(self.project, self.issue, self.draft)
                self.draft["assessment"]["local_subject_sha256"] = ids["local"]
                self.draft["assessment"]["composition_subject_sha256"] = ids["composition"]
                result = self.report()
                self.assertEqual(result["references"]["status"], "invalid")
                self.assertEqual(result["local_correspondence"]["status"], "unknown")
                self.assertEqual(result["composition"]["status"], "unknown")

    def test_applicable_negative_project_judgment_propagates_with_other_unknown(self):
        self.project["assessment"]["conclusion"] = "discrepancy"
        result = self.report()
        self.assertEqual(result["local_correspondence"]["status"], "discrepancy_reported")
        self.assertEqual(result["composition"]["status"], "discrepancy_reported")
        self.assertEqual(result["next_action"]["status"], "discrepancy_reported")
        self.issue["sources"].append({"key": "missing", "kind": "local_file", "location": str(self.root / "missing"),
            "sha256": "0" * 64, "applicability": "required", "basis": "fixture", "owner": "owner", "status": "current"})
        self.issue["assessment"]["subject_sha256"] = subjects(self.project, self.issue, self.draft)["issue"]
        self.draft["assessment"]["composition_subject_sha256"] = subjects(self.project, self.issue, self.draft)["composition"]
        result = self.report()
        self.assertIn("source_unavailable", result["source_coverage"]["findings"])
        self.assertEqual(result["composition"]["status"], "discrepancy_reported")
        self.assertEqual(result["next_action"]["status"], "discrepancy_reported")

    def test_stale_negative_project_judgment_is_not_treated_as_current(self):
        self.project["assessment"]["conclusion"] = "discrepancy"
        self.project["assessment"]["subject_sha256"] = "f" * 64
        result = self.report()
        self.assertEqual(result["assessments"]["project"]["applicability"], "stale")
        self.assertEqual(result["local_correspondence"]["status"], "unknown")

    def test_missing_canonical_fragment_does_not_apply_negative_project_judgment(self):
        self.project["assessment"]["conclusion"] = "discrepancy"
        self.project["canonical_entry"]["fragment"] = "absent"
        self.project["assessment"]["subject_sha256"] = subjects(self.project, self.issue, self.draft)["project"]
        result = self.report()
        self.assertEqual(result["assessments"]["project"]["applicability"], "stale")
        self.assertNotEqual(result["local_correspondence"]["status"], "discrepancy_reported")

    def test_implementation_action_requires_matching_open_native_draft(self):
        action = {"kind": "implement", "description": "Implement the plan"}
        self.draft["trace"]["action"] = action
        self.issue["assessment"]["actions"][0]["action"] = action
        ids = subjects(self.project, self.issue, self.draft)
        self.draft["assessment"]["local_subject_sha256"] = ids["local"]
        self.draft["assessment"]["composition_subject_sha256"] = ids["composition"]
        self.draft["assessment"]["readiness"]["action"] = action
        result = self.report()
        self.assertEqual(result["composition"]["status"], "supported_by_applicable_assessment")
        self.assertEqual(result["next_action"]["status"], "unknown")
        self.assertFalse(result["next_action"]["native_predicates_met"])

    def test_matching_open_draft_satisfies_native_implementation_predicate(self):
        action = {"kind": "implement", "description": "Implement the plan"}
        self.draft["trace"]["action"] = action
        self.draft["candidate"]["native_pr"] = {"number": 2, "node_id": "PR_two"}
        self.issue["assessment"]["actions"][0]["action"] = action
        ids = subjects(self.project, self.issue, self.draft)
        self.draft["assessment"]["local_subject_sha256"] = ids["local"]
        self.draft["assessment"]["composition_subject_sha256"] = ids["composition"]
        self.draft["assessment"]["readiness"]["action"] = action

        from graphvon.draft_contracts import parse_draft_project
        reader = LocalReader(parse_draft_project(self.project), "working")
        observed = native_pr(reader, self.issue["issue"], self.draft["candidate"]["native_pr"])
        self.draft["assessment"]["readiness"]["native_context"] = bind_receipt(self.project, self.issue, self.draft, observed)
        result = check(self.project, self.issue, self.draft, "working", reader, native_pr)
        self.assertEqual(result["next_action"]["status"], "supported_by_applicable_assessment")
        self.draft["candidate"]["body"] += "Changed"
        result = check(self.project, self.issue, self.draft, "working", reader, native_pr)
        self.assertFalse(result["next_action"]["native_predicates_met"])

    def test_project_profile_change_stales_its_assessment(self):
        self.project["profiles"][0]["sections"][0]["required"] = False
        with self.assertRaises(Refusal):
            self.report()

    def test_checker_does_not_modify_input_records(self):
        before = deepcopy((self.project, self.issue, self.draft))
        self.report()
        self.assertEqual((self.project, self.issue, self.draft), before)

    def test_native_issue_discussion_mismatch_holds_local_correspondence(self):
        def changed_discussion(reader, issue, pr):
            result = native(reader, issue, pr)
            result["observation"]["issue_comments"] = [{"id": "new"}]
            return result

        from graphvon.draft_contracts import parse_draft_project
        reader = LocalReader(parse_draft_project(self.project), "working")
        result = check(self.project, self.issue, self.draft, "working", reader, changed_discussion)
        self.assertFalse(result["local_correspondence"]["native_issue_matches"])
        self.assertEqual(result["local_correspondence"]["status"], "unknown")

    def test_equal_scope_labels_do_not_override_compatibility_discrepancy(self):
        self.draft["trace"]["scope"] = self.issue["scope"]
        self.draft["assessment"]["scope"] = self.issue["scope"]
        ids = subjects(self.project, self.issue, self.draft)
        self.draft["assessment"]["local_subject_sha256"] = ids["local"]
        self.draft["assessment"]["composition_subject_sha256"] = ids["composition"]
        self.draft["assessment"]["joint_constraints"] = {"result": "discrepancy", "reasons": ["Incompatible conditions"]}
        self.assertEqual(self.report()["composition"]["status"], "discrepancy_reported")

    def test_missing_installed_template_is_not_replaced_with_working_file(self):
        class MissingTemplate(LocalReader):
            def read(self, source):
                if source.key == "form": raise Refusal("Installed source absent")
                return super().read(source)

        from graphvon.draft_contracts import parse_draft_project
        reader = MissingTemplate(parse_draft_project(self.project), "installed")
        result = check(self.project, self.issue, self.draft, "installed", reader, native)
        self.assertIn("template_unavailable", result["structure"]["findings"])
        self.assertEqual(result["next_action"]["status"], "unknown")

    def test_changed_review_or_branch_stales_action_only_and_reaffirmation_restores(self):
        observed = self.implementation_fixture()
        self.assertEqual(self.report_with_native(observed)["next_action"]["status"], "supported_by_applicable_assessment")
        changed = deepcopy(observed)
        changed["observation"]["discussions"]["pull_request_reviews"].append({"id": "R_review", "updated_at": None,
            "submitted_at": "2026-11-13T00:00:00Z", "content_sha256": "b" * 64})
        result = self.report_with_native(changed)
        self.assertEqual(result["action_context"]["applicability"], "stale")
        self.assertIn("discussions.pull_request_reviews", result["action_context"]["differences"])
        self.assertEqual(result["next_action"]["status"], "unknown")
        self.assertEqual(result["composition"]["status"], "supported_by_applicable_assessment")
        moved = deepcopy(observed); moved["observation"]["pr"]["head"]["sha"] = "b" * 40
        moved["observation"]["pr"]["base"]["sha"] = "c" * 40
        result = self.report_with_native(moved)
        self.assertEqual(result["action_context"]["applicability"], "stale")
        self.assertIn("pull_request.head.commit", result["action_context"]["differences"])
        self.assertIn("pull_request.base.commit", result["action_context"]["differences"])
        self.draft["assessment"]["readiness"]["native_context"] = bind_receipt(self.project, self.issue, self.draft, moved)
        self.assertEqual(self.report_with_native(moved)["next_action"]["status"], "supported_by_applicable_assessment")

    def test_missing_receipt_or_unknown_judgment_never_supports_implementation(self):
        observed = self.implementation_fixture()
        receipt = self.draft["assessment"]["readiness"].pop("native_context")
        result = self.report_with_native(observed)
        self.assertEqual(result["action_context"]["applicability"], "not_assessed")
        self.assertEqual(result["next_action"]["status"], "unknown")
        receipt["applicability"] = {"result": "unknown", "reasons": ["No current assessment"]}
        self.draft["assessment"]["readiness"]["native_context"] = receipt
        self.assertEqual(self.report_with_native(observed)["next_action"]["status"], "unknown")

    def test_receipt_digest_cannot_be_reused_for_another_action_or_semantic_basis(self):
        observed = self.implementation_fixture()
        receipt = self.draft["assessment"]["readiness"]["native_context"]
        receipt["subject_sha256"] = "f" * 64
        self.assertEqual(self.report_with_native(observed)["action_context"]["applicability"], "stale")
        receipt.update(bind_receipt(self.project, self.issue, self.draft, observed))
        self.draft["trace"]["action"]["description"] = "A different action"
        result = self.report_with_native(observed)
        self.assertEqual(result["action_context"]["applicability"], "stale")
        self.assertIn("receipt_binding", result["action_context"]["differences"])
        self.draft["trace"]["action"]["description"] = "Implement the plan"
        self.draft["trace"]["remaining"].append("A new material condition")
        self.assertEqual(self.report_with_native(observed)["action_context"]["applicability"], "stale")

    def test_applicable_context_discrepancy_survives_other_unknown_prerequisite(self):
        observed = self.implementation_fixture()
        self.draft["assessment"]["readiness"]["native_context"]["applicability"] = {"result": "discrepancy", "reasons": ["Review requires a decision"]}
        self.issue["assessment"]["actions"][0]["adequacy"] = {"result": "unknown", "reasons": ["Independent question"]}
        ids = subjects(self.project, self.issue, self.draft)
        self.draft["assessment"]["composition_subject_sha256"] = ids["composition"]
        self.draft["assessment"]["readiness"]["native_context"] = bind_receipt(self.project, self.issue, self.draft, observed,
            {"result": "discrepancy", "reasons": ["Review requires a decision"]})
        result = self.report_with_native(observed)
        self.assertEqual(result["next_action"]["status"], "discrepancy_reported")
        self.assertEqual(result["action_context"]["declared_judgment"]["result"], "discrepancy")

    def test_candidate_only_discussion_without_pr_remains_supported(self):
        result = self.report()
        self.assertEqual(result["next_action"]["basis"], "candidate_only")
        self.assertEqual(result["action_context"]["requirement"], "candidate_only")
        self.assertEqual(result["next_action"]["status"], "supported_by_applicable_assessment")

    def test_declared_context_without_current_pr_is_unavailable(self):
        observed = native_pr(None, None, None)
        self.draft["assessment"]["readiness"]["native_context"] = bind_receipt(self.project, self.issue, self.draft, observed)
        result = self.report()
        self.assertEqual(result["action_context"]["requirement"], "declared")
        self.assertEqual(result["action_context"]["applicability"], "unavailable")
        self.assertEqual(result["next_action"]["status"], "unknown")
        self.assertEqual(result["next_action"]["basis"], "native_context_bound")

    def test_stale_negative_context_remains_historical_not_current_discrepancy(self):
        observed = self.implementation_fixture()
        self.draft["assessment"]["readiness"]["native_context"]["applicability"] = {"result": "discrepancy", "reasons": ["Old context"]}
        moved = deepcopy(observed); moved["observation"]["pr"]["head"]["sha"] = "b" * 40
        result = self.report_with_native(moved)
        self.assertEqual(result["action_context"]["applicability"], "stale")
        self.assertEqual(result["action_context"]["declared_judgment"]["result"], "discrepancy")
        self.assertEqual(result["next_action"]["status"], "unknown")

"""Behavioral checks with controlled source observations, not a semantic oracle."""

from contextlib import redirect_stdout
from copy import deepcopy
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from graphvon.contracts import Refusal, canonical_json
from graphvon.issue_contracts import (
    load_form, parse_project, parse_proposal, project_subject, render, text_digest,
)
from graphvon.issue_check import SourceReader, check, main, read_text


FORM = """name: Change
description: Describe an outcome.
body:
  - type: markdown
    attributes:
      value: Instruction text is not submitted content.
  - type: textarea
    id: behavior
    attributes:
      label: Requested behavior
    validations:
      required: true
  - type: textarea
    id: checks
    attributes:
      label: Acceptance
    validations:
      required: true
  - type: textarea
    id: questions
    attributes:
      label: Questions
"""
RULES = "# Contributing\n\n## Issues\nPreserve the requested outcome.\n"
GOAL = "Support both CSV and JSON exports.\n"


def reassess_project(project):
    project["assessment"] = {"subject_sha256": project_subject(project),
                             "provenance": "Separate fixture assessment", "scope": project["scope"],
                             "conclusion": "supported", "limits": []}


def make_project(root):
    sources = [
        ("rules", "repository_file", "CONTRIBUTING.md", RULES),
        ("form", "repository_file", "change.yml", FORM),
        ("goal", "local_file", str(root / "private-source.txt"), GOAL),
    ]
    for _, kind, location, value in sources:
        path = root / location if kind == "repository_file" else Path(location)
        path.write_text(value)
    project = {"version": 1, "root": str(root), "repository": {"name": "example/project", "id": "R_example"},
               "canonical_entry": {"source": "rules", "fragment": "issues"},
               "sources": [{"key": key, "kind": kind, "location": location, "sha256": text_digest(value),
                            "applicability": "required", "basis": "Declared project scope", "owner": "Fixture owner",
                            "status": "accepted"} for key, kind, location, value in sources],
               "allowed_templates": ["form"], "scope": "issue_proposal", "assessment": {}}
    reassess_project(project)
    return project


def make_proposal():
    return {"schema_version": 1, "artifact_id": "local-proposal", "record_revision": "1",
            "candidate": {"template": "form", "title": "Export both supported formats",
                          "fields": {"behavior": "Export CSV and JSON.", "checks": "Check both formats."},
                          "relationships": []},
            "trace": {"source_keys": ["rules", "form", "goal"], "scope": "issue_proposal", "next_action": "discuss_issue",
                      "conditions": [], "remaining": [], "unknowns": [],
                      "obligations": [{"id": "formats", "sources": ["goal"], "fields": ["behavior", "checks"],
                                       "coverage": "covered", "rationale": "Both requested formats are named."}]},
            "assessment": None}


class LocalReader(SourceReader):
    """The unit-level semantic cases assume repository binding was observed."""

    def prepare(self):
        pass


def assess(project, proposal, root, **results):
    basis = parse_project(project)
    report = check(basis, parse_proposal(proposal), "working", LocalReader(basis, "working"))
    proposal["assessment"] = {"subject_sha256": report["subject_sha256"],
                             "scope": "issue_proposal", "provenance": "Independent fixture expectation", "limits": []}
    for name in ("preservation", "definition", "readiness", "publication"):
        proposal["assessment"][name] = {"result": results.get(name, "supported"), "reasons": ["Synthetic scoped judgment"]}
    proposal["assessment"]["readiness"]["action"] = proposal["trace"]["next_action"]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="graphvon-issue-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = make_project(self.root)
        self.proposal = make_proposal()


class CheckTests(Fixture):
    def run_check(self):
        basis = parse_project(self.project)
        return check(basis, parse_proposal(self.proposal), "working", LocalReader(basis, "working"))

    def test_valid_short_proposal_does_not_infer_semantic_assessment(self):
        result = self.run_check()
        self.assertEqual(result["structure"]["status"], "valid")
        self.assertEqual(result["source_coverage"]["status"], "consistent_with_assessed_basis")
        self.assertEqual(result["semantic_assessment"]["applicability"], "not_assessed")
        self.assertEqual(result["public_payload"], {"title": "Export both supported formats",
            "body": "### Requested behavior\n\nExport CSV and JSON.\n\n### Acceptance\n\nCheck both formats.\n"})

    def test_omitting_required_source_cannot_narrow_project_basis(self):
        self.proposal["trace"]["source_keys"].remove("goal")
        result = self.run_check()
        self.assertEqual(result["structure"]["status"], "valid")
        self.assertIn("required_source_omitted", result["source_coverage"]["findings"])
        self.assertIn("trace_reference_mismatch", result["source_coverage"]["findings"])

    def test_changed_project_projection_invalidates_its_old_assessment(self):
        self.project["sources"][2]["applicability"] = "not_applicable"
        result = self.run_check()
        self.assertIn("project_assessment_stale", result["source_coverage"]["findings"])

    def test_unknown_applicability_and_missing_source_are_partial(self):
        self.project["sources"][2]["applicability"] = "unknown"
        reassess_project(self.project)
        self.assertIn("source_applicability_unknown", self.run_check()["source_coverage"]["findings"])
        self.project["sources"][2]["applicability"] = "required"
        reassess_project(self.project)
        (self.root / "private-source.txt").unlink()
        self.assertIn("source_unavailable", self.run_check()["source_coverage"]["findings"])

    def test_missing_template_is_distinct_from_unapproved_selection(self):
        (self.root / "change.yml").unlink()
        self.assertIn("template_unavailable", self.run_check()["structure"]["findings"])
        self.proposal["candidate"]["template"] = "rules"
        self.assertIn("template_not_permitted", self.run_check()["structure"]["findings"])

    def test_permitted_alternative_and_arbitrary_project_field_identifiers(self):
        alternative = FORM.replace("behavior", "request").replace("checks", "verification")
        (self.root / "alternative.yml").write_text(alternative)
        self.project["sources"].append({**self.project["sources"][1], "key": "alternative",
                                        "location": "alternative.yml", "sha256": text_digest(alternative)})
        self.project["allowed_templates"].append("alternative")
        reassess_project(self.project)
        self.proposal["candidate"].update(template="alternative", fields={"request": "Both formats.", "verification": "Check both."})
        self.proposal["trace"]["source_keys"].append("alternative")
        self.proposal["trace"]["obligations"][0]["fields"] = ["request", "verification"]
        result = self.run_check()
        self.assertEqual(result["structure"]["status"], "valid")
        self.assertEqual(result["source_coverage"]["status"], "consistent_with_assessed_basis")

    def test_form_required_and_unknown_fields_are_checked(self):
        self.proposal["candidate"]["fields"]["behavior"] = " "
        self.proposal["candidate"]["fields"]["undeclared"] = "not a declared field"
        result = self.run_check()
        self.assertEqual(set(result["structure"]["findings"]), {"missing_required_field", "unknown_field"})
        self.assertIsNone(result["public_payload"])

    def test_changed_content_invalidates_assessment_but_bookkeeping_does_not(self):
        assess(self.project, self.proposal, self.root)
        first = self.run_check()
        self.proposal.update(record_revision="2", operation={"phase": "observed"}, observation={"native_id": "I_sample"})
        second = self.run_check()
        self.assertEqual(first["subject_sha256"], second["subject_sha256"])
        self.assertEqual(second["semantic_assessment"]["applicability"], "matches_subject")
        self.proposal["candidate"]["fields"]["behavior"] = "CSV only."
        self.assertEqual(self.run_check()["semantic_assessment"]["applicability"], "stale_or_unresolved")

    def test_source_change_and_readiness_action_require_reassessment(self):
        assess(self.project, self.proposal, self.root)
        (self.root / "private-source.txt").write_text("JSON is also required offline.\n")
        result = self.run_check()
        self.assertIn("source_changed", result["source_coverage"]["findings"])
        self.assertEqual(result["semantic_assessment"]["applicability"], "stale_or_unresolved")
        (self.root / "private-source.txt").write_text(GOAL)
        self.proposal["assessment"]["readiness"]["action"] = "implement"
        self.assertEqual(self.run_check()["semantic_assessment"]["applicability"], "stale_or_unresolved")

    def test_semantic_findings_are_reported_not_replaced_by_shape_success(self):
        # These judgments are fixture inputs, not results of an automated LLM.
        scenarios = [
            ("CSV only.", "discrepancy", "supported", "unknown"),
            ("Both formats require a new mandatory archive fingerprint.", "discrepancy", "supported", "unknown"),
            ("Both formats using the accepted component interface.", "supported", "supported", "supported"),
            ("Both formats; decide the offline behavior.", "supported", "unknown", "unknown"),
        ]
        for behavior, preservation, definition, readiness in scenarios:
            with self.subTest(behavior=behavior):
                self.proposal = make_proposal()
                self.proposal["candidate"]["fields"]["behavior"] = behavior
                assess(self.project, self.proposal, self.root, preservation=preservation, definition=definition, readiness=readiness)
                result = self.run_check()
                self.assertEqual(result["structure"]["status"], "valid")
                self.assertEqual(result["semantic_assessment"]["declared_results"]["preservation"], preservation)
                self.assertEqual(result["semantic_assessment"]["declared_results"]["definition"], definition)
                self.assertFalse(result["semantic_assessment"]["performed_by_checker"])

    def test_private_metadata_is_not_rendered_and_publication_judgment_stays_separate(self):
        secret = "/private/synthetic/working-note.txt"
        operation_secret = "/private/synthetic/operation-only.txt"
        self.proposal["trace"]["obligations"][0]["rationale"] = secret
        self.proposal["operation"] = {"private_locator": operation_secret}
        assess(self.project, self.proposal, self.root)
        result = self.run_check()
        self.assertNotIn(secret, json.dumps(result["public_payload"]))
        self.assertEqual(result["declared_trace"]["obligations"][0]["rationale"], secret)
        self.assertNotIn(operation_secret, json.dumps(result))
        self.proposal["candidate"]["fields"]["behavior"] = "Use " + secret
        assess(self.project, self.proposal, self.root, publication="discrepancy")
        result = self.run_check()
        self.assertEqual(result["semantic_assessment"]["declared_results"]["publication"], "discrepancy")
        self.assertFalse(result["semantic_assessment"]["performed_by_checker"])

    def test_private_report_preserves_partial_scope_reasons_limits_and_remainder(self):
        self.project["assessment"]["limits"] = ["Source selection assessed for proposal discussion only."]
        trace = self.proposal["trace"]
        trace["next_action"] = "discuss_csv_scope"
        trace["conditions"] = ["Only the CSV branch is assessed."]
        trace["remaining"] = ["JSON export remains required."]
        trace["unknowns"] = ["Offline behavior is unresolved."]
        trace["obligations"][0]["coverage"] = "partial"
        assess(self.project, self.proposal, self.root, definition="unknown", readiness="unknown")
        assessment = self.proposal["assessment"]
        assessment["limits"] = ["This assessment does not establish implementation readiness."]
        assessment["preservation"]["reasons"] = ["The JSON obligation remains visible outside the assessed branch."]
        assessment["readiness"]["reasons"] = ["Clarify offline behavior before selecting the implementation."]
        result = self.run_check()
        self.assertEqual(result["declared_trace"], trace)
        semantic = result["semantic_assessment"]
        self.assertEqual(semantic["applicability"], "matches_subject")
        self.assertEqual(semantic["declared_scope"], assessment["scope"])
        self.assertEqual(semantic["judgment_context"]["readiness_action"], "discuss_csv_scope")
        self.assertEqual(semantic["judgment_context"]["reasons"]["readiness"], assessment["readiness"]["reasons"])
        self.assertEqual(semantic["judgment_context"]["limits"], assessment["limits"])
        self.assertEqual(result["source_coverage"]["project_assessment"]["limits"], self.project["assessment"]["limits"])
        public = json.dumps(result["public_payload"])
        self.assertNotIn("Only the CSV branch", public)
        self.assertNotIn("Offline behavior", public)
        result["declared_trace"]["remaining"].clear()
        result["semantic_assessment"]["judgment_context"]["limits"].clear()
        self.assertTrue(trace["remaining"])
        self.assertTrue(assessment["limits"])

    def test_partial_report_retains_context_before_assessment_can_be_checked(self):
        assess(self.project, self.proposal, self.root)
        self.proposal["trace"]["unknowns"] = ["Unresolved source applicability."]
        (self.root / "change.yml").unlink()
        result = self.run_check()
        self.assertEqual(result["semantic_assessment"]["applicability"], "not_checked")
        self.assertEqual(result["declared_trace"]["unknowns"], ["Unresolved source applicability."])
        self.assertEqual(result["semantic_assessment"]["judgment_context"]["readiness_action"], "discuss_issue")

    def test_canonical_fragment_in_code_block_is_not_an_entry(self):
        value = "# Example\n```text\n## Issues\n```\n"
        (self.root / "CONTRIBUTING.md").write_text(value)
        self.project["sources"][0]["sha256"] = text_digest(value)
        reassess_project(self.project)
        self.assertIn("canonical_entry_fragment_missing", self.run_check()["source_coverage"]["findings"])

    def test_only_a_real_closing_fence_exposes_the_canonical_heading(self):
        for fence in ("```", "~~~"):
            for suffix, expected in (("example", False), (" \t", True)):
                with self.subTest(fence=fence, suffix=suffix):
                    value = "# Example\n" + fence + "text\n" + fence + suffix + "\n## Issues\n"
                    (self.root / "CONTRIBUTING.md").write_text(value)
                    self.project["sources"][0]["sha256"] = text_digest(value)
                    reassess_project(self.project)
                    findings = self.run_check()["source_coverage"]["findings"]
                    self.assertEqual("canonical_entry_fragment_missing" not in findings, expected)

    def test_check_does_not_modify_inputs(self):
        before_project, before_proposal = deepcopy(self.project), deepcopy(self.proposal)
        before_files = {path.name: path.read_bytes() for path in self.root.iterdir()}
        self.run_check()
        self.assertEqual(self.project, before_project)
        self.assertEqual(self.proposal, before_proposal)
        self.assertEqual(before_files, {path.name: path.read_bytes() for path in self.root.iterdir()})


class FormTests(unittest.TestCase):
    def test_native_field_identifier_grammar_and_distinct_ids_with_same_labels(self):
        for invalid in ("need with space", "need!"):
            with self.subTest(identifier=invalid), self.assertRaises(Refusal):
                load_form(FORM.replace("id: behavior", "id: " + invalid))
        form = load_form(FORM.replace("id: behavior", "id: need_2-X").replace("label: Acceptance", "label: Requested behavior"))
        payload, errors = render(form, "Both formats", {"need_2-X": "CSV and JSON.", "checks": "Check both."})
        self.assertEqual(errors, [])
        self.assertEqual(payload["body"].count("### Requested behavior"), 2)

    def test_unsafe_yaml_duplicate_keys_identifiers_and_unknown_widgets_refuse(self):
        candidates = ["!!python/object/apply:os.system ['false']", FORM + "name: Other\n",
                      FORM.replace("id: checks", "id: behavior"), FORM.replace("type: textarea", "type: dropdown", 1)]
        for candidate in candidates:
            with self.subTest(candidate=candidate[:40]), self.assertRaises(Refusal):
                load_form(candidate)

    def test_defaults_and_code_fences_preserve_submitted_content(self):
        source = """name: Example
description: Example form.
title: Default title
body:
  - type: textarea
    id: details
    attributes:
      label: Example
      value: Default content
      render: text
    validations:
      required: true
"""
        form = load_form(source)
        payload, errors = render(form, "", {})
        self.assertEqual(errors, [])
        self.assertEqual(payload["title"], "Default title")
        payload, _ = render(form, "Example", {"details": "```\nembedded fence"})
        self.assertIn("````text\n```\nembedded fence\n````", payload["body"])


class ReaderTests(Fixture):
    def transport(self, arguments, **kwargs):
        self.commands.append(arguments)
        if arguments[0] == "git":
            if arguments[-1] == "--show-toplevel":
                output = str(self.root)
            elif arguments[-2:] == ["get-url", "origin"]:
                output = "git@github.com:example/project.git"
            else:
                raise AssertionError("Unexpected Git operation")
        else:
            self.assertEqual(arguments[:4], ["gh", "api", "--method", "GET"])
            endpoint = next(value for value in arguments if value.startswith("repos/"))
            if endpoint in self.failures:
                return subprocess.CompletedProcess(arguments, 1, "", "/private/synthetic/credential-location")
            value = self.responses[endpoint]
            output = value if isinstance(value, str) else json.dumps(value)
        return subprocess.CompletedProcess(arguments, 0, output, "")

    def setUp(self):
        super().setUp()
        self.commands = []
        self.failures = set()
        self.responses = {"repos/example/project": {"node_id": "R_example", "full_name": "example/project", "default_branch": "main"},
                          "repos/example/project/commits/main": {"sha": "a" * 40}}

    def test_installed_sources_come_from_pinned_default_branch(self):
        for source in self.project["sources"]:
            if source["kind"] == "repository_file":
                value = (self.root / source["location"]).read_bytes()
                endpoint = "repos/example/project/contents/" + source["location"] + "?ref=" + "a" * 40
                self.responses[endpoint] = {"type": "file", "encoding": "base64", "content": base64.b64encode(value).decode()}
        (self.root / "change.yml").write_text("This local replacement is not installed.")
        with patch("graphvon.issue_check.subprocess.run", side_effect=self.transport):
            result = check(parse_project(self.project), parse_proposal(self.proposal), "installed")
        self.assertEqual(result["mode"], "installed_profile")
        self.assertEqual(result["structure"]["status"], "valid")
        self.assertEqual(result["source_coverage"]["status"], "consistent_with_assessed_basis")

    def test_wrong_repository_and_remote_failure_are_unknown(self):
        self.responses["repos/example/project"]["node_id"] = "R_other"
        with patch("graphvon.issue_check.subprocess.run", side_effect=self.transport):
            result = check(parse_project(self.project), parse_proposal(self.proposal), "working")
        self.assertEqual(result["source_coverage"]["status"], "unknown")
        self.responses["repos/example/project"]["node_id"] = "R_example"
        self.failures.add("repos/example/project")
        with patch("graphvon.issue_check.subprocess.run", side_effect=self.transport):
            result = check(parse_project(self.project), parse_proposal(self.proposal), "working")
        self.assertNotIn("credential-location", json.dumps(result))

    def test_native_issue_comments_are_in_the_source_revision(self):
        prefix = "repos/example/project/issues/7"
        self.responses[prefix] = {"node_id": "I_seven", "number": 7, "title": "Need", "body": "Both formats",
                                  "repository_url": "https://api.github.com/repos/example/project"}
        self.responses[prefix + "/comments?per_page=100"] = []
        self.project["sources"][2].update(kind="github_issue", location=7)
        reader = SourceReader(parse_project(self.project), "working")
        with patch("graphvon.issue_check.subprocess.run", side_effect=self.transport):
            original = reader.read(reader.project.sources[2])
            self.responses[prefix + "/comments?per_page=100"] = [
                {"id": 9, "node_id": "IC_nine", "body": "Clarification", "user": None,
                 "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"}]
            changed = reader.read(reader.project.sources[2])
        self.assertNotEqual(text_digest(original), text_digest(changed))
        self.assertTrue(any("--paginate" in command for command in self.commands))

    def test_empty_or_partial_native_collection_is_not_success(self):
        reader = SourceReader(parse_project(self.project), "working")
        endpoint = "repos/example/project/issues/7/comments?per_page=100"
        self.responses[endpoint] = ""
        with patch("graphvon.issue_check.subprocess.run", side_effect=self.transport), self.assertRaises(Refusal):
            reader._get(endpoint, paginated=True)
        self.failures.add(endpoint)
        with patch("graphvon.issue_check.subprocess.run", side_effect=self.transport), self.assertRaises(Refusal):
            reader._get(endpoint, paginated=True)

    def test_cli_success_and_invalid_input_leave_records_unchanged(self):
        project_file = self.root / "basis.json"
        proposal_file = self.root / "proposal.json"
        project_file.write_text(json.dumps(self.project))
        proposal_file.write_text(json.dumps(self.proposal))
        request = {"version": 1, "project_basis": str(project_file), "proposal": str(proposal_file), "mode": "working"}
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        output = io.StringIO()
        with patch("graphvon.issue_check.subprocess.run", side_effect=self.transport), patch("sys.stdin", io.StringIO(json.dumps(request))), redirect_stdout(output):
            self.assertEqual(main(["check"]), 0)
        self.assertEqual(json.loads(output.getvalue())["structure"]["status"], "valid")
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.root.iterdir()})
        request["proposal"] = "/private/synthetic/missing-proposal.json"
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(request))), redirect_stdout(output):
            self.assertEqual(main(["check"]), 2)
        self.assertNotIn("missing-proposal", output.getvalue())

    def test_regular_file_read_preserves_bytes_and_refuses_fifo(self):
        path = self.root / "line-endings.txt"
        path.write_bytes(b"line1\r\nline2\r\n")
        self.assertEqual(read_text(path), "line1\r\nline2\r\n")
        if hasattr(os, "mkfifo"):
            fifo = self.root / "source-pipe"
            os.mkfifo(fifo)
            with self.assertRaises(Refusal):
                read_text(fifo)


if __name__ == "__main__":
    unittest.main()

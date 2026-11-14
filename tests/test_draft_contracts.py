"""Reference and subject behavior for the documented Draft profile."""

import unittest

from graphvon.contracts import Refusal, canonical_json
from graphvon.draft_contracts import action_context_subject, native_context, resolve_source_ref, scan_markdown, source_ref
from graphvon.issue_contracts import Source


class ReferenceTests(unittest.TestCase):
    def test_native_body_offsets_are_not_serialized_json_offsets(self):
        source = Source("goal", "github_issue", 1, "0" * 64, "required", "fixture")
        native = canonical_json({"id": "I_one", "body": "á target target", "comments": []})
        selector = {"source": "issue:goal", "selector": {"kind": "exact", "target": "issue_body", "start": 9, "end": 15, "text": "target"}}
        source_ref(selector)
        self.assertEqual(resolve_source_ref(selector, source, native, "I_one"), ("target", None))
        selector["selector"]["start"] = 0
        self.assertEqual(resolve_source_ref(selector, source, native, "I_one")[1], "selection_text_mismatch")

    def test_sections_ignore_comments_and_fences_and_reject_duplicates(self):
        source = Source("rules", "local_file", "/tmp/rules", "0" * 64, "required", "fixture")
        ref = {"source": "project:rules", "selector": {"kind": "markdown_section", "target": "source_text", "heading": "Plan"}}
        value = "<!-- ## Plan -->\n```\n## Plan\n<!-- literal -->\n```\n## Plan\nUseful\n### Details\nMore\n## Next\n"
        selected, finding = resolve_source_ref(ref, source, value)
        self.assertIsNone(finding)
        self.assertEqual(selected, "## Plan\nUseful\n### Details\nMore\n")
        self.assertEqual(resolve_source_ref(ref, source, value + "## Plan\nagain\n")[1], "heading_ambiguous")
        self.assertIn("markdown_profile_unsupported", scan_markdown("Heading\n=======\n")["findings"])

    def test_invalid_selector_refuses_before_source_access(self):
        with self.assertRaises(Refusal):
            source_ref({"source": "project:rules", "selector": {"kind": "exact", "target": "source_text", "start": True, "end": 4, "text": "test"}})

    def test_html_is_not_implicitly_parsed_as_markdown(self):
        source = Source("guide", "local_file", "/tmp/guide.html", "0" * 64, "required", "fixture")
        ref = {"source": "issue:guide", "selector": {"kind": "markdown_section", "target": "source_text", "heading": "Plan"}}
        self.assertEqual(resolve_source_ref(ref, source, "## Plan\nText\n")[1], "selector_target_unsupported")
        ref["selector"] = {"kind": "exact", "target": "source_text", "start": 0, "end": 2, "text": "##"}
        self.assertEqual(resolve_source_ref(ref, source, "## Plan\nText\n"), ("##", None))

    def test_inline_comment_token_is_content_but_real_comments_are_masked(self):
        literal = scan_markdown("## Plan\nUse `<!--` literally.\n")
        self.assertEqual(literal["findings"], [])
        self.assertIn("`<!--`", literal["content"])
        comment = scan_markdown("## Plan\n<!-- placeholder -->\n")
        heading = comment["headings"][0]
        self.assertFalse(comment["content"][heading["content_start"]:heading["end"]].strip())
        self.assertIn("markdown_profile_unsupported", scan_markdown("## Plan\n<!-- unfinished\n")["findings"])

    def test_fenced_literal_comment_token_does_not_open_comment(self):
        scanned = scan_markdown("```text <!-- literal\n<!--\n```\n## Plan\nUseful\n")
        self.assertEqual(scanned["findings"], [])
        self.assertEqual([h["heading"] for h in scanned["headings"]], ["Plan"])

    def test_multiline_inline_code_preserves_literal_comment_and_next_heading(self):
        value = "## Plan\nParse `a\n<!--\nb` literally.\n## Next\nMore.\n"
        scanned = scan_markdown(value)
        self.assertEqual(scanned["findings"], [])
        self.assertEqual([h["heading"] for h in scanned["headings"]], ["Plan", "Next"])
        self.assertIn("<!--", scanned["content"])

    def test_multiline_code_requires_matching_delimiter_run(self):
        value = "## Plan\nUse ``outer ` tick\n<!-- literal -->\nend`` here.\n## Next\nMore.\n"
        scanned = scan_markdown(value)
        self.assertEqual(scanned["findings"], [])
        self.assertIn("<!-- literal -->", scanned["content"])
        self.assertEqual([h["heading"] for h in scanned["headings"]], ["Plan", "Next"])

    def test_unmatched_tick_does_not_hide_real_comment(self):
        scanned = scan_markdown("## Plan\nUnmatched `tick\n<!-- real comment\n## Next\nMore.\n")
        self.assertIn("markdown_profile_unsupported", scanned["findings"])
        self.assertEqual([h["heading"] for h in scanned["headings"]], ["Plan"])
        self.assertNotIn("real comment", scanned["content"])

    def test_unmatched_tick_before_fence_does_not_change_block_precedence(self):
        value = "## Plan\nUnmatched `tick\n```\n<!-- literal\n```\n## Next\nMore.\n"
        scanned = scan_markdown(value)
        self.assertEqual(scanned["findings"], [])
        self.assertEqual([h["heading"] for h in scanned["headings"]], ["Plan", "Next"])

    def test_context_digest_normalizes_order_and_detects_changed_envelope(self):
        branch = {"repository_id": "R_one", "ref": "main", "commit": "a" * 40}
        rows = [{"id": ident, "updated_at": None, "submitted_at": None, "content_sha256": "b" * 64} for ident in ("two", "one")]
        basis = {"repository": {"name": "example/project", "node_id": "R_one"},
                 "issue": {"number": 1, "node_id": "I_one", "state": "open", "title": "Goal", "body": "Text"},
                 "pull_request": {"number": 2, "node_id": "PR_two", "state": "open", "draft": True, "title": "Plan", "body": "Text", "head": branch, "base": branch},
                 "discussions": {"issue_comments": [], "pull_request_issue_comments": [], "pull_request_reviews": rows, "pull_request_review_comments": []}}
        action = {"kind": "implement", "description": "Implement"}; ids = {"local": "1" * 64, "composition": "2" * 64}
        first = action_context_subject(action, "scope", ids, basis)
        rows.reverse()
        self.assertEqual(first, action_context_subject(action, "scope", ids, basis))
        self.assertEqual([r["id"] for r in native_context(basis)["discussions"]["pull_request_reviews"]], ["one", "two"])
        rows[0]["content_sha256"] = "c" * 64
        self.assertNotEqual(first, action_context_subject(action, "scope", ids, basis))
        rows.append(dict(rows[0]))
        with self.assertRaises(Refusal): native_context(basis)

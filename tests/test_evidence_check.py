import contextlib
from copy import deepcopy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from graphvon.evidence_check import _selection, check, main
from graphvon.evidence_contracts import identity


def record():
    reference = {"locator": "/receipt", "selector": {"kind": "exact", "start": 0, "end": 4}, "provenance": "producer"}
    return {"id": "s", "original": reference.copy(), "current": reference.copy(), "retained_text": "text", "continuity": None}


def closure_fixture():
    issue = {"obligations": [{"id": "o"}], "shared_constraints": [], "conditions": [], "assessment": None}
    draft = {"trace": {"effects": [{"id": "e"}]}, "assessment": None}
    hist = {"records": [{"assessment": None}, issue, draft], "subjects": {}, "bindings": {"project": True}, "identity": "history"}
    app = {"scope": {"obligation_ids": ["o"], "constraint_ids": [], "property": "plan"}, "current_conditions": [], "assessment": None}
    obs = {"id": "obs", "selection_id": "s", "kind": "planned", "original_subject": {"kind": "retained", "description": "plan"}, "result": "planned", "conditions": [], "limits": [], "applications": [app]}
    v = {"version": 1, "scope": "scope", "upstream": {"current_source_mode": "working", "applicability": None}, "change": {}, "selections": [record()], "observations": [obs],
         "correspondence": {"effects": [{"effect_id": "e", "disposition": "realized", "change_ids": ["c"], "observation_ids": ["obs"], "reason": "mapped"}], "changes": [{"change_id": "c", "effect_ids": ["e"], "justification": "mapped"}], "assessment": None},
         "claim": {"conclusion": "complete", "obligations": [{"id": "o", "disposition": "supported", "observation_ids": [{"id": "obs", "application": 0}], "reason": "reviewed", "remainder": ""}], "constraints": [], "conditions": [], "remainder": [], "limits": []}, "joint_assessment": None, "decision": None}
    return hist, v


def judgment(subject, result="supported"):
    return {"subject": subject, "result": result, "provenance": "review", "reasons": [], "limits": []}


class CheckTests(unittest.TestCase):
 def test_assessment_invalid_values_preserve_partial_report(self):
    hist, value = closure_fixture()
    args = {"receipt_reader": lambda _: "text", "current_reader": lambda *_: {"sources": {}, "native": {}}, "git_reader": lambda _: {"identity": "change", "entries": [{"id": "c"}]}}
    with patch("graphvon.evidence_check.historical", return_value=hist):
        for placement in ("upstream", "correspondence", "joint", "application", "continuity"):
            for field, malformed in ((None, []), (None, {}), (None, 0), ("result", []), ("result", {}), ("result", 0), ("subject", []), ("provenance", []), ("reasons", {}), ("limits", {})):
                candidate = deepcopy(value)
                invalid = judgment("a" * 64)
                if field is None: invalid = malformed
                else: invalid[field] = malformed
                if placement == "upstream": candidate["upstream"]["applicability"] = invalid
                elif placement == "correspondence": candidate["correspondence"]["assessment"] = invalid
                elif placement == "joint": candidate["joint_assessment"] = invalid
                elif placement == "application": candidate["observations"][0]["applications"][0]["assessment"] = invalid
                else: candidate["selections"][0]["continuity"] = invalid
                report = check(candidate, **args)
                assert report["git_changes"]["status"] == "available"
                assert report["evidence"][0]["id"] == "obs"
                assert report["supplied"]["status"] == "unvalidated"
                selected = {"upstream": report["current_applicability"]["assessment"], "correspondence": report["correspondence"]["assessment"], "joint": report["claim"]["joint_assessment"], "application": report["evidence"][0]["applications"][0]["assessment"], "continuity": report["selections"][0]["continuity"]}[placement]
                assert selected["status"] == "invalid" and selected["declared"] == invalid

 def test_partial_and_complete_require_enumeration(self):
    hist, value = closure_fixture()
    hist["records"][1]["shared_constraints"] = [{"id": "constraint"}]
    hist["records"][1]["conditions"] = [{"id": "condition"}]
    value["claim"]["obligations"][0]["observation_ids"] = []
    value["claim"]["constraints"] = [{"id": "constraint", "disposition": "supported", "observation_ids": [], "reason": "reviewed", "remainder": ""}]
    value["claim"]["conditions"] = [{"id": "condition", "disposition": "satisfied", "observation_ids": [], "reason": "reviewed"}]
    args = {"receipt_reader": lambda _: "text", "current_reader": lambda *_: {"sources": {}, "native": {}}, "git_reader": lambda _: {"identity": "change", "entries": [{"id": "c"}]}}
    with patch("graphvon.evidence_check.historical", return_value=hist):
        report = check(value, **args)
        value["upstream"]["applicability"] = judgment(report["current_applicability"]["assessment"]["subject"])
        value["correspondence"]["assessment"] = judgment(report["correspondence"]["assessment"]["subject"])
        for conclusion in ("complete", "partial"):
            candidate = deepcopy(value); candidate["claim"]["conclusion"] = conclusion
            if conclusion == "partial":
                candidate["claim"]["obligations"][0]["disposition"] = "unknown"
                candidate["claim"]["remainder"] = ["unfinished"]
            valid = check(candidate, **args)
            assert valid["claim"]["status"] == "consistent" and valid["claim"]["current_usability"] == "usable"
            for category in ("obligations", "constraints", "conditions"):
                omitted = deepcopy(candidate); omitted["claim"][category] = []
                missing = check(omitted, **args)
                assert missing["claim"]["current_usability"] != "usable"
                assert category in missing["claim"]["missing"] and missing["claim"]["missing"][category]
                assert any(c["component"] == "claim_enumeration" for c in missing["claim"]["causes"])

 def test_required_continuity_and_receipt_failures_both_visible(self):
    hist, value = closure_fixture()
    value["selections"][0]["current"]["locator"] = "/moved"
    receipts = {"/moved": "text"}
    def read(path):
        if path not in receipts: raise OSError("missing")
        return receipts[path]
    args = {"receipt_reader": read, "current_reader": lambda *_: {"sources": {}, "native": {}}, "git_reader": lambda _: {"identity": "change", "entries": [{"id": "c"}]}}
    with patch("graphvon.evidence_check.historical", return_value=hist):
        first = check(value, **args)
        value["selections"][0]["continuity"] = judgment(first["selections"][0]["continuity"]["subject"], "discrepancy")
        receipts.clear()
        for direct in (True, False):
            candidate = deepcopy(value)
            if not direct: candidate["claim"]["obligations"][0]["observation_ids"] = []
            report = check(candidate, **args)
            assert {c["state"] for c in report["correspondence"]["causes"]} >= {"unavailable", "discrepancy"}
            if direct:
                assert any(c["component"] == "application_selection" and c["state"] == "unavailable" for c in report["claim"]["causes"])
                assert any(c["component"] == "application_continuity" and c["state"] == "discrepancy" for c in report["claim"]["causes"])
        receipts["/moved"] = "new!"
        changed = check(value, **args)
        assert {c["state"] for c in changed["correspondence"]["causes"]} >= {"stale", "discrepancy"}
        value["selections"][0]["continuity"]["result"] = "supported"
        receipts["/moved"] = "text"
        assert check(value, **args)["selections"][0]["usable"]
        unchanged = deepcopy(value); unchanged["selections"][0]["current"] = deepcopy(unchanged["selections"][0]["original"])
        unchanged["selections"][0]["continuity"]["result"] = "discrepancy"
        receipts["/receipt"] = "text"
        assert all(c.get("component") != "continuity" for c in check(unchanged, **args)["correspondence"]["causes"])

 def test_reference_closure_binding_and_support(self):
    hist, value = closure_fixture()
    receipts = {"/receipt": "text"}
    def read(path):
        if path not in receipts: raise OSError("missing")
        return receipts[path]
    args = {"receipt_reader": read, "current_reader": lambda *_: {"sources": {}, "native": {}}, "git_reader": lambda _: {"identity": "change", "entries": [{"id": "c"}]}}
    with patch("graphvon.evidence_check.historical", return_value=hist):
        r = check(value, **args)
        value["upstream"]["applicability"] = judgment(r["current_applicability"]["assessment"]["subject"])
        value["correspondence"]["assessment"] = judgment(r["correspondence"]["assessment"]["subject"])
        value["observations"][0]["applications"][0]["assessment"] = judgment(r["evidence"][0]["applications"][0]["assessment"]["subject"])
        r = check(value, **args)
        value["joint_assessment"] = judgment(r["claim"]["subject"])
        value["decision"] = {"claim_subject": r["claim"]["subject"], "joint_assessment_subject": identity("joint_assessment", value["joint_assessment"]), "outcome": "not_accepted", "authority": "owner", "provenance": "record", "reasons": [], "limits": []}
        r = check(value, **args)
        assert r["claim"]["current_usability"] == "usable" and r["decision"]["current_usability"] == "usable"
        assert r["decision"]["declared"]["outcome"] == "not_accepted"
        before = (r["correspondence"]["assessment"]["subject"], r["claim"]["subject"])
        typed_change = deepcopy(value)
        typed_change["observations"][0]["kind"] = "reported_execution"
        typed_report = check(typed_change, **args)
        assert typed_report["evidence"][0]["applications"][0]["assessment"]["status"] == "stale"
        assert typed_report["correspondence"]["assessment"]["status"] == "stale"
        assert typed_report["claim"]["subject"] != before[1]
        value["observations"][0]["applications"][0]["scope"]["property"] = "reported execution"
        changed_property = check(value, **args)
        value["observations"][0]["applications"][0]["assessment"] = judgment(changed_property["evidence"][0]["applications"][0]["assessment"]["subject"])
        rebound = check(value, **args)
        assert rebound["claim"]["current_usability"] == "usable"
        value["observations"][0]["applications"][0]["scope"]["property"] = "plan"
        original_target = check(value, **args)["evidence"][0]["applications"][0]["assessment"]["subject"]
        value["observations"][0]["applications"][0]["assessment"] = judgment(original_target)
        unused = deepcopy(record()); unused["id"] = "unused"; unused["current"]["locator"] = "/missing"
        value["selections"].append(unused)
        extra = deepcopy(value["observations"][0]); extra["id"] = "other"; extra["selection_id"] = "unused"; extra["applications"] = []
        value["observations"].append(extra)
        r = check(value, **args)
        assert (r["correspondence"]["assessment"]["subject"], r["claim"]["subject"]) == before
        assert r["decision"]["current_usability"] == "usable"
        receipts.clear()
        r = check(value, **args)
        assert (r["correspondence"]["assessment"]["subject"], r["claim"]["subject"]) == before
        assert r["decision"]["status"] == "matches" and r["decision"]["current_usability"] != "usable"
        receipts["/receipt"] = "new!"
        r = check(value, **args)
        assert r["claim"]["subject"] == before[1] and r["claim"]["current_usability"] != "usable"
        receipts["/receipt"] = "text"
        value["observations"][0]["original_subject"]["description"] = "other source"
        r = check(value, **args)
        assert r["correspondence"]["assessment"]["subject"] != before[0] and r["claim"]["subject"] != before[1]

 def test_malformed_uncited_child_and_declaration_retention(self):
    hist, value = closure_fixture()
    value["observations"][0]["applications"].append({"bad": "child"})
    args = {"receipt_reader": lambda _: "text", "current_reader": lambda *_: {"sources": {}, "native": {}}, "git_reader": lambda _: {"identity": "change", "entries": [{"id": "c"}]}}
    with patch("graphvon.evidence_check.historical", return_value=hist):
        r = check(value, **args)
        assert r["evidence"][0]["applications"][0]["assessment"]["subject"]
        assert r["evidence"][0]["applications"][1]["status"] == "invalid"
        assert r["correspondence"]["assessment"]["subject"]
        value["claim"]["obligations"][0]["observation_ids"][0]["application"] = 1
        r = check(value, **args)
        assert r["claim"]["current_usability"] != "usable"
        assert not any(e.get("to", {}).get("index") == 1 for e in r["graph_edges"])
    with patch("graphvon.evidence_check.historical", side_effect=OSError("missing")):
        r = check(value, **args)
        assert r["claim"]["declared"] == value["claim"]
        assert r["correspondence"]["declared"]["effects"] == value["correspondence"]["effects"]
        assert r["evidence"][0]["declared"]["result"] == "planned"

 def test_correspondence_states_and_simultaneous_failures(self):
    hist, value = closure_fixture()
    args = {"receipt_reader": lambda _: "text", "current_reader": lambda *_: {"sources": {}, "native": {}}, "git_reader": lambda _: {"identity": "change", "entries": [{"id": "c"}]}}
    with patch("graphvon.evidence_check.historical", return_value=hist):
        r = check(value, **args)
        value["upstream"]["applicability"] = judgment(r["current_applicability"]["assessment"]["subject"])
        subject = r["correspondence"]["assessment"]["subject"]
        for verdict, expected in (("supported", "usable"), ("discrepancy", "discrepancy"), ("unknown", "unknown")):
            value["correspondence"]["assessment"] = judgment(subject, verdict)
            assert check(value, **args)["correspondence"]["current_usability"] == expected
        value["correspondence"]["assessment"] = None
        assert check(value, **args)["correspondence"]["current_usability"] == "not_assessed"
        value["correspondence"]["assessment"] = judgment("0" * 64)
        assert check(value, **args)["correspondence"]["current_usability"] == "stale"
        value["correspondence"]["assessment"] = judgment(subject, "discrepancy")
        args["current_reader"] = lambda *_: (_ for _ in ()).throw(OSError("unavailable"))
        r = check(value, **args)
        assert {x["state"] for x in r["claim"]["causes"]} >= {"discrepancy", "unavailable"}
        assert r["current_applicability"]["assessment"]["declared"] == value["upstream"]["applicability"]

 def test_correspondence_only_observation_and_uncited_child(self):
    hist, value = closure_fixture()
    value["claim"]["obligations"][0]["observation_ids"] = []
    args = {"receipt_reader": lambda _: "text", "current_reader": lambda *_: {"sources": {}, "native": {}}, "git_reader": lambda _: {"identity": "change", "entries": [{"id": "c"}]}}
    with patch("graphvon.evidence_check.historical", return_value=hist):
        first = check(value, **args)
        before = (first["correspondence"]["assessment"]["subject"], first["claim"]["subject"])
        value["observations"][0]["applications"].append({"malformed": True})
        after = check(value, **args)
        assert (after["correspondence"]["assessment"]["subject"], after["claim"]["subject"]) == before
        assert after["evidence"][0]["applications"][1]["status"] == "invalid"
        value["observations"][0]["applications"][0]["scope"]["property"] = "unrelated edit"
        after = check(value, **args)
        assert (after["correspondence"]["assessment"]["subject"], after["claim"]["subject"]) == before
        value["observations"][0]["original_subject"]["description"] = "other"
        after = check(value, **args)
        assert after["correspondence"]["assessment"]["subject"] != before[0]
        assert after["claim"]["subject"] != before[1]

 def test_partial_claim_retains_remainder_without_contradiction(self):
    hist, value = closure_fixture()
    value["claim"]["conclusion"] = "partial"
    value["claim"]["obligations"][0]["disposition"] = "partial"
    value["claim"]["obligations"][0]["remainder"] = "unfinished"
    value["claim"]["remainder"] = ["unfinished"]
    args = {"receipt_reader": lambda _: "text", "current_reader": lambda *_: {"sources": {}, "native": {}}, "git_reader": lambda _: {"identity": "change", "entries": [{"id": "c"}]}}
    with patch("graphvon.evidence_check.historical", return_value=hist):
        report = check(value, **args)
    assert report["claim"]["status"] == "consistent"
    assert report["claim"]["declared"]["remainder"] == ["unfinished"]
 def test_selection_continuity_and_substitution(self):
    row = record()
    original = _selection(row, lambda _: "text appended")
    assert original["usable"] and original["status"] == "matches"
    row["current"] = {**row["current"], "locator": "/elsewhere"}
    moved = _selection(row, lambda _: "text")
    assert moved["status"] == "matches" and not moved["usable"]
    row["continuity"] = {"subject": moved["continuity"]["subject"], "result": "supported", "provenance": "review", "reasons": [], "limits": []}
    assert _selection(row, lambda _: "text")["usable"]
    changed = _selection(row, lambda _: "new!")
    assert changed["status"] == "changed" and not changed["usable"]


 def test_unavailable_historical_does_not_suppress_git(self):
    value = {"version": 1, "scope": "test", "upstream": {}, "change": {}, "selections": [record()], "observations": [], "correspondence": {}, "claim": {}, "joint_assessment": None, "decision": None}
    report = check(value, receipt_reader=lambda _: "text", git_reader=lambda _: {"identity": "change", "entries": []})
    assert report["historical_upstream"]["status"] == "unavailable"
    assert report["git_changes"]["status"] == "available"
    assert report["selections"][0]["usable"]
    decision = {"claim_subject": "historical", "joint_assessment_subject": "prior", "outcome": "accepted", "authority": "owner", "provenance": "record", "reasons": [], "limits": []}
    value["decision"] = decision
    report = check(value, receipt_reader=lambda _: "text", git_reader=lambda _: {"identity": "change", "entries": []})
    assert report["decision"]["declared"] == decision
    assert report["decision"]["status"] == "unavailable"
    assert report["decision"]["current_usability"] == "unavailable"

 def test_property_prose_does_not_define_execution_policy(self):
    value = {"version": 1, "scope": "test", "upstream": {}, "change": {}, "selections": [record()],
             "observations": [{"id": "o", "selection_id": "s", "kind": "planned", "original_subject": {"kind": "retained", "description": "plan"},
                 "result": "planned", "conditions": [], "limits": [], "applications": [{"scope": {"obligation_ids": [], "constraint_ids": [], "property": "reported_execution"}, "current_conditions": [], "assessment": None}]}],
             "correspondence": {}, "claim": {}, "joint_assessment": None, "decision": None}
    report = check(value, receipt_reader=lambda _: "text", git_reader=lambda _: {"identity": "change", "entries": []})
    assert report["evidence"][0]["applications"][0]["usable"]
    assert report["evidence"][0]["declared"]["result"] == "planned"
    original = report["evidence"][0]["original_identity"]
    value["observations"][0]["applications"][0]["scope"]["property"] = "reported execution"
    assert check(value, receipt_reader=lambda _: "text", git_reader=lambda _: {"identity": "change", "entries": []})["evidence"][0]["applications"][0]["usable"]
    value["observations"][0]["kind"] = "reported_execution"
    report = check(value, receipt_reader=lambda _: "text", git_reader=lambda _: {"identity": "change", "entries": []})
    assert report["evidence"][0]["applications"][0]["usable"]
    assert report["evidence"][0]["original_identity"] != original

 def test_duplicate_malformed_observation_is_partial(self):
    issue = {"obligations": [], "shared_constraints": [], "conditions": [], "assessment": None}
    draft = {"trace": {"effects": []}, "assessment": None}
    hist = {"records": [{"assessment": None}, issue, draft], "subjects": {}, "bindings": {}, "identity": "history"}
    obs = {"id": "o", "selection_id": "s", "kind": "planned", "original_subject": {"kind": "retained", "description": "plan"}, "result": "planned", "conditions": [], "limits": [], "applications": []}
    value = {"version": 1, "scope": "test", "upstream": {"current_source_mode": "working", "applicability": None}, "change": {}, "selections": [record(), {"id": "s"}], "observations": [obs, {"id": "o"}], "correspondence": {"effects": [], "changes": [], "assessment": None}, "claim": {"conclusion": "partial", "obligations": [], "constraints": [], "conditions": [], "remainder": [], "limits": []}, "joint_assessment": None, "decision": None}
    with patch("graphvon.evidence_check.historical", return_value=hist):
        report = check(value, current_reader=lambda *_: {"sources": {}, "native": {}}, receipt_reader=lambda _: "text", git_reader=lambda _: {"identity": "change", "entries": []})
    assert report["git_changes"]["status"] == "available"
    assert len(report["evidence"]) == 1
    assert {x["code"] for x in report["findings"]} >= {"invalid_selection", "invalid_observation"}

 def test_current_prerequisite_and_inspectable_graph(self):
    issue = {"obligations": [{"id": "o"}], "shared_constraints": [], "conditions": [], "assessment": None}
    draft = {"trace": {"effects": [{"id": "e"}]}, "assessment": None}
    hist = {"records": [{"assessment": None}, issue, draft], "subjects": {}, "bindings": {}, "identity": "history"}
    value = {"version": 1, "scope": "test", "upstream": {"current_source_mode": "working", "applicability": None}, "change": {}, "selections": [record()],
             "observations": [{"id": "obs", "selection_id": "s", "kind": "native_observation", "original_subject": {"kind": "retained", "description": "source"}, "result": "observed", "conditions": ["condition"], "limits": ["limit"], "applications": []}],
             "correspondence": {"effects": [{"effect_id": "e", "disposition": "realized", "change_ids": ["c"], "observation_ids": ["obs"], "reason": "mapped"}], "changes": [{"change_id": "c", "effect_ids": ["e"], "justification": "mapped"}], "assessment": None},
             "claim": {"conclusion": "complete", "obligations": [{"id": "o", "disposition": "supported", "observation_ids": [], "reason": "inspected", "remainder": ""}], "constraints": [], "conditions": [], "remainder": [], "limits": ["bounded"]}, "joint_assessment": None, "decision": None}
    observed = {"sources": {"project:rules": {"status": "matches", "sha256": "a"}}, "native": {"state": "merged"}}
    read = lambda *_: observed
    args = {"current_reader": read, "receipt_reader": lambda _: "text", "git_reader": lambda _: {"identity": "change", "entries": [{"id": "c"}]}}
    with patch("graphvon.evidence_check.historical", return_value=hist):
        first = check(value, **args)
        value["upstream"]["applicability"] = {"subject": first["current_applicability"]["assessment"]["subject"], "result": "supported", "provenance": "review", "reasons": [], "limits": []}
        value["correspondence"]["assessment"] = {"subject": first["correspondence"]["assessment"]["subject"], "result": "supported", "provenance": "review", "reasons": [], "limits": []}
        supported = check(value, **args)
        value["joint_assessment"] = {"subject": supported["claim"]["subject"], "result": "supported", "provenance": "review", "reasons": [], "limits": []}
        value["decision"] = {"claim_subject": supported["claim"]["subject"], "joint_assessment_subject": identity("joint_assessment", value["joint_assessment"]), "outcome": "accepted", "authority": "owner", "provenance": "record", "reasons": [], "limits": []}
        supported = check(value, **args)
        assert supported["claim"]["current_usability"] == "usable"
        assert supported["claim"]["joint_assessment"]["current_usability"] == "usable"
        assert supported["decision"]["current_usability"] == "usable"
        assert supported["evidence"][0]["declared"]["original_subject"]["description"] == "source"
        assert supported["correspondence"]["declared"]["effects"][0]["effect_id"] == "e"
        assert supported["claim"]["declared"]["limits"] == ["bounded"]
        assert any(e["type"] == "observation_selection" for e in supported["graph_edges"])
        old_subject = supported["claim"]["subject"]
        observed["sources"]["project:rules"]["sha256"] = "b"
        stale = check(value, **args)
        assert stale["claim"]["subject"] == old_subject
        assert stale["claim"]["current_usability"] == "stale"
        assert stale["claim"]["joint_assessment"]["status"] == "applicable"
        assert stale["claim"]["joint_assessment"]["current_usability"] == "stale"
        assert stale["decision"]["status"] == "matches"
        assert stale["decision"]["current_usability"] == "stale"
        observed["sources"]["project:rules"]["sha256"] = "a"
        value["upstream"]["applicability"]["result"] = "discrepancy"
        assert check(value, **args)["claim"]["current_usability"] == "discrepancy"
        value["upstream"]["applicability"]["result"] = "unknown"
        assert check(value, **args)["claim"]["current_usability"] == "unknown"
        observed["sources"]["project:rules"]["status"] = "unavailable"
        assert check(value, **args)["claim"]["current_usability"] == "unavailable"


 def test_cli_invalid_root(self):
    with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as output:
        path = Path(directory) / "bad.json"; path.write_text('{"version": 1, "version": 1}')
        assert main(["check", "--input", str(path)]) == 2
        assert 'invalid_input' in output.getvalue()

 def test_document_only_claim_and_historical_decision(self):
    issue = {"obligations": [{"id": "o"}], "shared_constraints": [], "conditions": [], "assessment": None}
    draft = {"trace": {"effects": [{"id": "e"}]}, "assessment": None}
    hist = {"records": [{"assessment": None}, issue, draft], "subjects": {}, "bindings": {}, "identity": "history"}
    value = {"version": 1, "scope": "document", "upstream": {"current_source_mode": "working", "applicability": None},
             "change": {}, "selections": [], "observations": [],
             "correspondence": {"effects": [{"effect_id": "e", "disposition": "realized", "change_ids": ["c"], "observation_ids": [], "reason": "content"}],
                                "changes": [{"change_id": "c", "effect_ids": ["e"], "justification": "content"}], "assessment": None},
             "claim": {"conclusion": "complete", "obligations": [{"id": "o", "disposition": "supported", "observation_ids": [], "reason": "inspected", "remainder": ""}],
                       "constraints": [], "conditions": [], "remainder": [], "limits": []}, "joint_assessment": None, "decision": None}
    # No universal execution observation is required; semantic assessment stays separate.
    current = lambda *_: {"sources": {}, "native": {"state": "merged"}}
    git = lambda _: {"identity": "change", "entries": [{"id": "c"}]}
    with patch("graphvon.evidence_check.historical", return_value=hist):
        report = check(value, current_reader=current, git_reader=git)
        assert report["claim"]["status"] == "consistent"
        value["upstream"]["applicability"] = judgment(report["current_applicability"]["assessment"]["subject"])
        value["correspondence"]["assessment"] = judgment(report["correspondence"]["assessment"]["subject"])
        report = check(value, current_reader=current, git_reader=git)
        value["joint_assessment"] = judgment(report["claim"]["subject"])
        report = check(value, current_reader=current, git_reader=git)
        assert report["claim"]["joint_assessment"]["current_usability"] == "usable"
        value["correspondence"]["effects"][0]["disposition"] = "partial"
        assert check(value, current_reader=current, git_reader=git)["claim"]["status"] == "inconsistent"
        value["correspondence"]["effects"][0]["disposition"] = "realized"
        value["decision"] = {"claim_subject": report["claim"]["subject"], "joint_assessment_subject": "old", "outcome": "accepted", "authority": "owner", "provenance": "record", "reasons": [], "limits": []}
        value["claim"]["remainder"] = ["unfinished"]
        report = check(value, current_reader=current, git_reader=git)
        assert report["claim"]["status"] == "inconsistent"
        assert report["decision"]["status"] == "stale"

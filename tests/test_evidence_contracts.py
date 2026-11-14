import unittest

from graphvon.contracts import Refusal
from graphvon.evidence_contracts import assessment, identity, root


class ContractTests(unittest.TestCase):
 def test_assessment_binding_preserves_stale_result(self):
    first = identity("subject", "first")
    other = identity("subject", "other")
    record = {"subject": first, "result": "supported", "provenance": "review", "reasons": [], "limits": []}
    assert assessment(record, first)["status"] == "applicable"
    assert assessment(record, other)["status"] == "stale"
    assert assessment(record, other)["declared"] == record
    assert assessment(None, first)["status"] == "not_assessed"


 def test_invalid_root_and_duplicate_json_keys(self):
    from graphvon.contracts import parse_json
    with self.assertRaises(Refusal):
        parse_json('{"version": 1, "version": 1}')
    with self.assertRaises(Refusal):
        root({"version": 1})

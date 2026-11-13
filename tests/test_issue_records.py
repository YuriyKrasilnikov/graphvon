"""Ordinary-file record and durable-boundary behavior."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from graphvon.contracts import Refusal
from graphvon.issue_records import load_record, save_record
from test_issue_check import make_proposal


class RecordTests(unittest.TestCase):
    def test_revision_and_nonordinary_file_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record"
            path.write_text(json.dumps(make_proposal()))
            with self.assertRaises(Refusal):
                load_record(path, "stale")
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(Refusal):
                load_record(link, "1")

    def test_failed_sync_reports_unknown_and_cleans_owned_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record"
            record = make_proposal()
            path.write_text(json.dumps(record))
            with patch("graphvon.issue_records.os.fsync", side_effect=OSError("failed")):
                with self.assertRaises(Refusal):
                    save_record(path, record)
            self.assertEqual(list(Path(directory).iterdir()), [path])

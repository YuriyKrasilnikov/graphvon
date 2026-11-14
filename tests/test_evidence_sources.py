import subprocess
import os
from unittest.mock import patch

import tempfile
from pathlib import Path
import unittest

from graphvon.contracts import Refusal
from graphvon.evidence_sources import git_change, select


class SourceTests(unittest.TestCase):
 def test_selection_boundaries(self):
    assert select("prefix evidence tail", {"kind": "exact", "start": 7, "end": 15}) == "evidence"
    assert select("## A\ntext\n## B\nmore\n", {"kind": "markdown_section", "heading": "A"}) == "text\n"
    with self.assertRaises(Refusal):
        select("## A\na\n## A\nb\n", {"kind": "markdown_section", "heading": "A"})


 def test_explicit_committed_pair_and_unusual_path(self):
    with tempfile.TemporaryDirectory() as directory:
     self.check_pair(Path(directory))

 def check_pair(self, tmp_path):
    def git(*args):
        return subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True).stdout.decode().strip()
    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "first").write_text("one")
    git("add", "."); git("commit", "-qm", "first")
    base = git("rev-parse", "HEAD")
    (tmp_path / "line\nbreak").write_text("two")
    git("add", "."); git("commit", "-qm", "second")
    end = git("rev-parse", "HEAD")
    (tmp_path / "first").write_text("uncommitted")
    result = git_change({"root": str(tmp_path), "base_commit": base, "result_commit": end})
    assert result["commits"] == [base, end]
    assert bytes.fromhex(result["entries"][0]["path_hex"]) == b"line\nbreak"
    assert len(result["entries"]) == 1
    with self.assertRaises(Refusal):
        git_change({"root": str(tmp_path), "base_commit": "HEAD", "result_commit": end})

 def test_named_repository_ignores_inherited_routing(self):
    with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
        def git(path, *args):
            return subprocess.run(["git", "-C", path, *args], check=True, capture_output=True).stdout.decode().strip()
        for path in (first, second):
            git(path, "init", "-q"); git(path, "config", "user.name", "Test"); git(path, "config", "user.email", "test@example.invalid")
            (Path(path) / "file").write_text(path); git(path, "add", "."); git(path, "commit", "-qm", "fixture")
        own = git(first, "rev-parse", "HEAD"); foreign = git(second, "rev-parse", "HEAD")
        with patch.dict(os.environ, {"GIT_DIR": str(Path(second) / ".git"), "GIT_WORK_TREE": second,
                                     "GIT_COMMON_DIR": str(Path(second) / ".git"),
                                     "GIT_OBJECT_DIRECTORY": str(Path(second) / ".git" / "objects"),
                                     "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(Path(second) / ".git" / "objects")}):
            assert git_change({"root": first, "base_commit": own, "result_commit": own})["commits"] == [own, own]
            with self.assertRaises(Refusal):
                git_change({"root": first, "base_commit": foreign, "result_commit": foreign})
        for variable, target in (("GIT_OBJECT_DIRECTORY", Path(second) / ".git" / "objects"),
                                 ("GIT_ALTERNATE_OBJECT_DIRECTORIES", Path(second) / ".git" / "objects"),
                                 ("GIT_COMMON_DIR", Path(second) / ".git")):
            with patch.dict(os.environ, {variable: str(target)}):
                assert git_change({"root": first, "base_commit": own, "result_commit": own})["commits"] == [own, own]
                with self.assertRaises(Refusal):
                    git_change({"root": first, "base_commit": foreign, "result_commit": foreign})

 def test_historical_scope_is_distinct_from_subject(self):
    import json
    from test_draft_check import fixture
    from graphvon.evidence_sources import historical
    with tempfile.TemporaryDirectory() as directory:
        project, issue, draft = fixture(Path(directory))
        records = {"/project": project, "/issue": issue, "/draft": draft}
        upstream = {"project": "/project", "issue": "/issue", "draft": "/draft", "current_source_mode": "working", "applicability": None}
        read = lambda path: json.dumps(records[path])
        assert all(historical(upstream, read)["bindings"].values())
        project["assessment"]["scope"] = "unrelated"
        result = historical(upstream, read)
        assert result["binding_details"]["project"]["subject_matches"]
        assert not result["binding_details"]["project"]["scope_matches"]
        assert not result["bindings"]["project"]
        project, issue, draft = fixture(Path(directory))
        records.update({"/project": project, "/issue": issue, "/draft": draft})
        issue["assessment"]["scope"] = "unrelated"
        result = historical(upstream, read)
        assert result["binding_details"]["issue"]["subject_matches"]
        assert not result["bindings"]["issue"]
        project, issue, draft = fixture(Path(directory))
        records.update({"/project": project, "/issue": issue, "/draft": draft})
        draft["assessment"]["scope"] = "unrelated"
        result = historical(upstream, read)
        assert result["binding_details"]["draft_local"]["subject_matches"]
        assert result["binding_details"]["draft_composition"]["subject_matches"]
        assert not result["bindings"]["draft_local"] and not result["bindings"]["draft_composition"]

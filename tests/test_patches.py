"""Focused native grammar and local filesystem effect checks."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from graphvon.contracts import Grant, Refusal
from graphvon.patches import Effect, inspect_patch


def patch(body: str) -> str:
    return "*** Begin Patch\n" + body + "\n*** End Patch"


@unittest.skipUnless(os.name == "posix", "The initial patch profile is POSIX.")
class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="graphvon-patch-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "repo"
        self.root.mkdir()

    def inspect(self, body, *grants, cwd=None):
        return inspect_patch(patch(body), cwd or self.root, self.root, grants)

    def write(self, path, contents="before\n"):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
        return target

    def test_add_content_is_parsed_without_mutation(self):
        effects = self.inspect(
            "*** Add File: new.txt\n+hello\n+*** Delete File: other.txt\n+",
            Grant("add", "new.txt"),
        )
        self.assertEqual(effects, (Effect("add", "new.txt"),))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_empty_addition_and_all_native_file_operations(self):
        self.write("removed.txt")
        self.write("changed.txt")
        effects = self.inspect(
            "*** Add File: empty.txt\n"
            "*** Delete File: removed.txt\n"
            "*** Update File: changed.txt\n@@\n-before\n+after",
            Grant("add", "empty.txt"),
            Grant("delete", "removed.txt"),
            Grant("update", "changed.txt"),
        )
        self.assertEqual(effects, (
            Effect("add", "empty.txt"),
            Effect("delete", "removed.txt"),
            Effect("update", "changed.txt"),
        ))
        self.assertFalse((self.root / "empty.txt").exists())
        self.assertEqual((self.root / "removed.txt").read_text(), "before\n")

    def test_update_forms_and_context_that_resembles_a_header(self):
        source = self.write("file.txt")
        bodies = (
            "-before\n+after",
            "@@\n-before\n+after",
            "@@ named context\n context\n-before\n+after\n@@\n+last",
            "\n context\n+after",
            "@@\n-before\n+after\n*** End of File\n\n  ",
            "@@\n-first\n+second\n*** End of File\n@@\n+third",
            " *** Add File: context.txt\n+after",
            "@@\n+one\u2028two\vthree",
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual(
                    self.inspect("*** Update File: file.txt\n" + body,
                                 Grant("update", "file.txt")),
                    (Effect("update", "file.txt"),),
                )
        self.assertEqual(source.read_text(), "before\n")

    def test_native_header_whitespace_crlf_and_exact_wrappers(self):
        direct = " \t*** Begin Patch \n  *** Add File: file.txt \n+line\n *** End Patch\n"
        for command in (
            direct,
            direct.replace("\n", "\r\n"),
            "<<EOF\n" + direct + "EOF\n",
            "<<'EOF'\n" + direct + "EOF\n",
            '<<"EOF"\n' + direct + "EOF\n",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    inspect_patch(command, self.root, self.root, (Grant("add", "file.txt"),)),
                    (Effect("add", "file.txt"),),
                )

    def test_malformed_or_shell_wrappers_are_refused(self):
        direct = patch("*** Add File: file.txt\n+line")
        for command in (
            "apply_patch <<'EOF'\n" + direct + "\nEOF",
            "<<EOF\n" + direct + "\ntrailingEOF",
            "<<EOF\n" + direct + "\nEOF\nextra",
            "<<EOF\n" + direct,
            "<<PATCH\n" + direct + "\nPATCH",
            direct + "\nextra",
        ):
            with self.subTest(command=command), self.assertRaises(Refusal):
                inspect_patch(command, self.root, self.root, (Grant("add", "file.txt"),))

    def test_malformed_grammar_is_refused_before_effect_acceptance(self):
        self.write("file.txt")
        malformed = (
            "*** Add File: file.txt\nunmarked content",
            "*** Add File: file.txt\n\n+line",
            "*** Delete File: file.txt\n-extra",
            "*** Update File: file.txt",
            "*** Update File: file.txt\n@@",
            "*** Update File: file.txt\n@@\n@@\n+line",
            "*** Update File: file.txt\n*** Move to: moved.txt",
            "*** Update File: file.txt\n*** Move to: moved.txt\n*** Move to: again.txt\n+line",
            "*** Update File: file.txt\n+line\n*** Move to: moved.txt",
            "*** Update File: file.txt\n@@\n*** End of File",
            "*** Update File: file.txt\n+line\n*** End of File\n+late",
            "*** Update File: file.txt\nunmarked content",
            "*** Add File: file.txt\n+line\n*** End Patch",
            "*** Add File: ",
            "*** Begin Patch",
            "\x1c*** Add File: file.txt\n+line",
        )
        grants = (
            Grant("add", "file.txt", True), Grant("update", "file.txt"),
            Grant("delete", "file.txt"), Grant("move_from", "file.txt"),
            Grant("move_to", "moved.txt"), Grant("move_to", "again.txt"),
        )
        for body in malformed:
            with self.subTest(body=body), self.assertRaises(Refusal):
                self.inspect(body, *grants)
        self.assertEqual((self.root / "file.txt").read_text(), "before\n")

    def test_empty_nontext_and_incomplete_patches_are_refused(self):
        for command in (None, 1, "", "*** Begin Patch", "*** End Patch",
                        "*** Begin Patch\n*** End Patch", "\ud800"):
            with self.subTest(command=repr(command)), self.assertRaises(Refusal):
                inspect_patch(command, self.root, self.root, ())

    def test_environment_directed_patch_is_outside_local_profile(self):
        with self.assertRaises(Refusal):
            self.inspect("*** Environment ID: remote\n*** Add File: file.txt\n+line",
                         Grant("add", "file.txt"))

    def test_paths_are_resolved_from_event_cwd(self):
        nested = self.root / "nested"
        nested.mkdir()
        for native_path in ("../file.txt", str(self.root / "file.txt")):
            with self.subTest(native_path=native_path):
                self.assertEqual(
                    self.inspect("*** Add File: " + native_path + "\n+line",
                                 Grant("add", "file.txt"), cwd=nested),
                    (Effect("add", "file.txt"),),
                )
        self.assertEqual(
            self.inspect("*** Add File: file.txt\n+line",
                         Grant("add", "nested/file.txt"), cwd=nested),
            (Effect("add", "nested/file.txt"),),
        )

    def test_component_containment_rejects_escape_and_prefix_siblings(self):
        sibling = self.root.with_name(self.root.name + "-sibling")
        for path in ("../outside.txt", str(sibling / "file.txt"), str(self.root),
                     "//ambiguous/file.txt", "file.txt/", "bad\0name"):
            with self.subTest(path=path), self.assertRaises(Refusal):
                self.inspect("*** Add File: " + path + "\n+line", Grant("add", "file.txt"))

    def test_invalid_roots_and_working_directories_are_refused(self):
        regular = self.write("file.txt")
        absent = self.root / "absent"
        linked = self.root.parent / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        cases = (
            (Path("relative"), self.root), (self.root, Path("relative")),
            (absent, self.root), (self.root, absent),
            (regular, self.root), (self.root, regular),
            (linked, self.root), (self.root, linked),
            (self.root.parent, self.root),
        )
        for cwd, root in cases:
            with self.subTest(cwd=cwd, root=root), self.assertRaises(Refusal):
                inspect_patch(patch("*** Add File: new.txt\n+line"), cwd, root,
                              (Grant("add", "new.txt"),))

    def test_each_new_parent_directory_requires_its_own_grant(self):
        body = "*** Add File: new/nested/file.txt\n+line"
        grants = (Grant("mkdir", "new"), Grant("mkdir", "new/nested"),
                  Grant("add", "new/nested/file.txt"))
        self.assertEqual(self.inspect(body, *grants), (
            Effect("mkdir", "new"), Effect("mkdir", "new/nested"),
            Effect("add", "new/nested/file.txt"),
        ))
        for missing in (0, 1):
            with self.subTest(missing=missing), self.assertRaises(Refusal):
                self.inspect(body, *(grants[:missing] + grants[missing + 1:]))
        self.assertFalse((self.root / "new").exists())

    def test_shared_new_parent_is_reported_once(self):
        self.assertEqual(self.inspect(
            "*** Add File: new/a.txt\n+a\n*** Add File: new/b.txt\n+b",
            Grant("mkdir", "new"), Grant("add", "new/a.txt"), Grant("add", "new/b.txt"),
        ), (Effect("mkdir", "new"), Effect("add", "new/a.txt"), Effect("add", "new/b.txt")))

    def test_move_checks_both_endpoints_and_new_parents(self):
        source = self.write("old.txt")
        body = "*** Update File: old.txt\n*** Move to: new/file.txt\n@@\n-before\n+after"
        grants = (Grant("move_from", "old.txt"), Grant("mkdir", "new"),
                  Grant("move_to", "new/file.txt"))
        self.assertEqual(self.inspect(body, *grants), (
            Effect("move_from", "old.txt"), Effect("mkdir", "new"),
            Effect("move_to", "new/file.txt"),
        ))
        for remaining in (grants[1:], grants[:-1]):
            with self.subTest(remaining=remaining), self.assertRaises(Refusal):
                self.inspect(body, *remaining)
        self.assertEqual(source.read_text(), "before\n")
        self.assertFalse((self.root / "new").exists())

    def test_add_and_move_replacement_need_explicit_admission(self):
        existing = self.write("existing.txt")
        self.write("source.txt")
        cases = (
            ("*** Add File: existing.txt\n+after", (), "add"),
            ("*** Update File: source.txt\n*** Move to: existing.txt\n-before\n+after",
             (Grant("move_from", "source.txt"),), "move_to"),
        )
        for body, initial, operation in cases:
            with self.subTest(operation=operation):
                with self.assertRaises(Refusal):
                    self.inspect(body, *initial, Grant(operation, "existing.txt"))
                effects = self.inspect(body, *initial, Grant(operation, "existing.txt", True))
                self.assertIn(Effect(operation, "existing.txt", True), effects)
        self.assertEqual(existing.read_text(), "before\n")

    def test_update_delete_and_move_source_must_exist(self):
        for body, grants in (
            ("*** Update File: absent.txt\n+line", (Grant("update", "absent.txt"),)),
            ("*** Delete File: absent.txt", (Grant("delete", "absent.txt"),)),
            ("*** Update File: absent.txt\n*** Move to: new.txt\n+line",
             (Grant("move_from", "absent.txt"), Grant("move_to", "new.txt"))),
        ):
            with self.subTest(body=body), self.assertRaises(Refusal):
                self.inspect(body, *grants)

    def test_symlink_endpoints_and_parent_components_are_refused(self):
        self.write("target.txt")
        (self.root / "file-link").symlink_to("target.txt")
        (self.root / "dangling-link").symlink_to("missing.txt")
        (self.root / "directory").mkdir()
        (self.root / "directory-link").symlink_to("directory", target_is_directory=True)
        for path in ("file-link", "dangling-link", "directory-link/new.txt"):
            with self.subTest(path=path), self.assertRaises(Refusal):
                self.inspect("*** Add File: " + path + "\n+line", Grant("add", path, True))

    def test_multiply_linked_and_special_endpoints_are_refused(self):
        original = self.write("original.txt")
        os.link(original, self.root / "alias.txt")
        os.mkfifo(self.root / "pipe")
        (self.root / "directory").mkdir()
        for path in ("original.txt", "alias.txt", "pipe", "directory"):
            with self.subTest(path=path), self.assertRaises(Refusal):
                self.inspect("*** Add File: " + path + "\n+line", Grant("add", path, True))
        with self.assertRaises(Refusal):
            self.inspect("*** Add File: original.txt/child\n+line",
                         Grant("add", "original.txt/child"))

    def test_repeated_and_overlapping_endpoints_are_explicitly_unsupported(self):
        self.write("existing.txt")
        for body, grants in (
            ("*** Add File: new.txt\n+one\n*** Add File: ./new.txt\n+two",
             (Grant("add", "new.txt", True),)),
            ("*** Add File: new\n+one\n*** Add File: new/child\n+two",
             (Grant("add", "new"), Grant("mkdir", "new"), Grant("add", "new/child"))),
            ("*** Update File: existing.txt\n*** Move to: existing.txt\n-before\n+after",
             (Grant("move_from", "existing.txt"), Grant("move_to", "existing.txt", True))),
        ):
            with self.subTest(body=body), self.assertRaisesRegex(Refusal, "unsupported"):
                self.inspect(body, *grants)

    def test_grants_are_exact_and_structurally_valid(self):
        body = "*** Add File: file.txt\n+line"
        for grants in (
            (), (Grant("update", "file.txt"),), (Grant("add", "other.txt"),),
            ({"operation": "add", "path": "file.txt"},),
            (Grant("add", "file.txt"), Grant("add", "file.txt")),
        ):
            with self.subTest(grants=grants), self.assertRaises(Refusal):
                self.inspect(body, *grants)
        with self.assertRaises(Refusal):
            inspect_patch(patch(body), self.root, self.root, [Grant("add", "file.txt")])


if __name__ == "__main__":
    unittest.main()

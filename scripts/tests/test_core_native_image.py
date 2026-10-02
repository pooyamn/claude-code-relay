"""Real ELF-like file bytes; substituted Linux proc/root metadata, no native CLI."""
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

from native_image_fixtures import executable_fixture
from relay_core import native_image
from relay_core.identity import Denied
from relay_core.native_image import NativeExecutable


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def pin(self, state, **changes):
        values = dict(pid=13, executable=state.executable, expected_digest=state.byte_digest)
        values.update(changes)
        return NativeExecutable(**values)

    def test_actual_file_bytes_and_inode_are_pinned_without_execution_or_retained_fd(self):
        with executable_fixture(self.tmp.name) as state:
            image = self.pin(state)
            self.assertTrue(image.digest.startswith("sha256:"))
            self.assertEqual(state.opened, set())
            reads = state.reads
            self.assertEqual(image.current(), image.digest)
            self.assertEqual(state.reads, reads)  # Revalidate immutable file metadata; no full-image read per frame.

    def test_no_platform_path_version_or_digest_fallback(self):
        with executable_fixture(self.tmp.name) as state:
            for changes in ({"pid": True}, {"pid": 0}, {"executable": "codex"},
                            {"executable": "/opt/ccrelay/native/../codex"}, {"executable": "/opt/ccrelay/native/v1//codex"},
                            {"executable": "/usr/bin/codex"}, {"expected_digest": "version-1"}):
                with self.subTest(changes=changes), self.assertRaises(Denied):
                    self.pin(state, **changes)
            with mock.patch.object(native_image.sys, "platform", "darwin"), self.assertRaises(Denied):
                self.pin(state)
            self.assertEqual(state.reads, 0)

    def test_matching_version_or_filename_cannot_replace_the_byte_pin(self):
        with executable_fixture(self.tmp.name) as state:
            with self.assertRaisesRegex(Denied, "ELF bytes"):
                self.pin(state, expected_digest="sha256:" + "a" * 64)

    def test_same_bytes_in_a_different_executed_inode_are_not_the_reviewed_install(self):
        with executable_fixture(self.tmp.name) as state:
            state.proc_target = state.other
            with self.assertRaisesRegex(Denied, "inode"):
                self.pin(state)

    def test_deleted_changed_or_interpreter_proc_path_cannot_supply_a_pin(self):
        with executable_fixture(self.tmp.name) as state:
            for link in (state.executable + " (deleted)", "/usr/bin/python3", "/tmp/codex", ""):
                state.link = link
                with self.assertRaises(Denied):
                    self.pin(state)
            self.assertEqual(state.reads, 0)

    def test_current_rejects_same_path_atomic_replacement_even_with_same_bytes(self):
        with executable_fixture(self.tmp.name) as state:
            image = self.pin(state)
            os.replace(state.other, state.path)
            with self.assertRaisesRegex(Denied, "metadata"):
                image.current()

    def test_current_rejects_in_place_image_write_or_permissions_change(self):
        with executable_fixture(self.tmp.name) as state:
            image = self.pin(state)
            state.path.chmod(0o700)
            state.path.write_bytes(b"\x7fELFaltered-image")
            state.path.chmod(0o500)
            with self.assertRaises(Denied):
                image.current()

    def test_unprotected_worker_owned_writable_or_privileged_images_are_rejected(self):
        with executable_fixture(self.tmp.name) as state:
            state.deny_path = True
            with self.assertRaises(Denied):
                self.pin(state)
            state.deny_path = False
            state.uid = 101
            with self.assertRaises(Denied):
                self.pin(state)
            state.uid = 0
            for mode in (0o522, 0o4500, 0o2500, 0o400):
                state.path.chmod(mode)
                # The Mac scratch filesystem strips both set-ID bits. Model
                # those Linux mode bits explicitly; don't weaken the gate.
                state.mode = stat.S_IFREG | mode if mode & 0o6000 else None
                with self.subTest(mode=oct(mode), actual_mode=oct(state.path.lstat().st_mode)), self.assertRaises(Denied):
                    self.pin(state)

    def test_hashing_cannot_confirm_an_image_changed_during_the_read(self):
        with executable_fixture(self.tmp.name) as state:
            state.after_read = lambda: setattr(state, "proc_target", state.other)
            with self.assertRaisesRegex(Denied, "during observation"):
                self.pin(state)

    def test_current_brackets_the_proc_image_reopen_and_path_observation(self):
        with executable_fixture(self.tmp.name) as state:
            image = self.pin(state)
            state.on_stat = lambda: setattr(state, "proc_target", state.other)
            with self.assertRaises(Denied):
                image.current()

    def test_non_elf_or_empty_candidate_is_not_silently_replaced_by_an_interpreter(self):
        with executable_fixture(self.tmp.name, body=b"#!/usr/bin/env python3\n") as state:
            with self.assertRaisesRegex(Denied, "ELF bytes"):
                self.pin(state)
        with tempfile.TemporaryDirectory() as empty, executable_fixture(empty, body=b"") as state:
            with self.assertRaises(Denied):
                self.pin(state)

    def test_missing_proc_access_denies_and_closes_the_installed_descriptor(self):
        with executable_fixture(self.tmp.name) as state:
            state.proc_target = Path(self.tmp.name) / "absent"
            with self.assertRaisesRegex(Denied, "observation unavailable"):
                self.pin(state)
            self.assertEqual(state.opened, set())

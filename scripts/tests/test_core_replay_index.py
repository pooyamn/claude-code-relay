"""Pinned Git debug framing and durable semantic-index manifest checks."""
import base64
import unittest

from relay_core.contracts import canonical_bytes
from relay_core.identity import Denied
from relay_core.replay_index import ASSUME, INTENT, SKIP, manifest, parse_index, path_bytes


def record(path=b"src/file", *, mode=b"100644", object_id=b"a" * 40, stage=b"0", flags=b"0"):
    return (mode + b" " + object_id + b" " + stage + b"\t" + path + b"\0" +
            b"  ctime: 1:2\n  mtime: 3:4\n  dev: 5\tino: 6\n  uid: 7\tgid: 8\n  size: 9\tflags: " + flags + b"\n")


class ReplayIndexTests(unittest.TestCase):
    def test_nul_paths_keep_newlines_tabs_non_utf8_and_semantic_flags(self):
        rows = parse_index(record(b"-dash\n\t\xff", flags=b"6000c000") + record(b"z", object_id=b"b" * 64), max_entries=2)
        self.assertEqual(path_bytes(rows[0]["path"]), b"-dash\n\t\xff")
        self.assertEqual(rows[0]["flags"], ASSUME | SKIP | INTENT)
        self.assertEqual(rows[1]["oid"], "b" * 64)

    def test_changed_debug_framing_truncation_unsafe_and_duplicated_paths_fail_closed(self):
        for raw in (record().replace(b"  uid:", b" uid:"), record()[:-1], record().replace(b"\0", b"\n"),
                    record(b"../outside"), record(b"x/.git/config"), record(b"x//file"), record(b"/absolute"),
                    record() + record(), record(b"z") + record(b"a"), record(b"x\0y")):
            with self.subTest(raw=raw):
                with self.assertRaises(Denied):
                    parse_index(raw, max_entries=8)

    def test_unmerged_gitlinks_sparse_directory_unknown_extended_flag_and_entry_bounds_hold(self):
        for raw in (record(stage=b"1"), record(flags=b"1000"), record(mode=b"160000"),
                    record(mode=b"040000", path=b"sparse/"), record(flags=b"80000000")):
            with self.assertRaises(Denied):
                parse_index(raw, max_entries=8)
        with self.assertRaises(Denied):
            parse_index(record(b"a") + record(b"b"), max_entries=1)

    def test_manifest_covers_flags_modes_object_id_presence_order_and_all_entries(self):
        rows = parse_index(record(b"a") + record(b"b"), max_entries=2)
        original = manifest(rows, "sha256:" + "c" * 64)
        for field, value in (("flags", ASSUME), ("mode", "100755"), ("oid", "f" * 40), ("present", True)):
            changed = [dict(row) for row in rows]
            changed[0][field] = value
            self.assertNotEqual(manifest(changed, original["raw_index_digest"]), original)
        self.assertNotEqual(manifest(rows[::-1], original["raw_index_digest"]), original)
        self.assertNotEqual(manifest(rows[:1], original["raw_index_digest"]), original)
        self.assertEqual(len(original["digest"]), 71)
        with self.assertRaises(Denied):
            path_bytes(base64.b64encode(b".git/config").decode())

    def test_many_long_paths_use_a_small_complete_manifest_not_inline_request_paths(self):
        raw = b"".join(record(str(number).zfill(5).encode() + b"x" * 100) for number in range(1000))
        rows = parse_index(raw, max_entries=1000)
        state = manifest(rows, "sha256:" + "c" * 64)
        self.assertEqual(state["count"], 1000)
        self.assertLess(len(canonical_bytes(state)), 300)
        self.assertGreater(sum(len(canonical_bytes(row)) for row in rows), 65536)

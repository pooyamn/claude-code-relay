import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import unittest

spec = importlib.util.spec_from_file_location('fpga_restore', Path(__file__).parents[1] / 'restore_pc_shared_fpga.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def archive(rows):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode='w:gz') as output:
        for name, body, kind in rows:
            item = tarfile.TarInfo(name); item.type = kind
            if kind == tarfile.REGTYPE:
                item.size = len(body); output.addfile(item, io.BytesIO(body))
            else:
                item.linkname = '/outside'; output.addfile(item)
    result.seek(0); return result


class SharedFpgaRestoreTests(unittest.TestCase):
    def setUp(self):
        self.body = b'\0original\xff'
        self.expected = {'original.bit': (len(self.body), hashlib.sha256(self.body).hexdigest())}

    def test_exact_binary_bytes_without_executing_siblings(self):
        data = archive([('Shared/fpga/original.bit', self.body, tarfile.REGTYPE),
                        ('Shared/other/run.sh', b'never execute', tarfile.REGTYPE)])
        self.assertEqual(module.gather(data, self.expected), {'original.bit': self.body})

    def test_duplicates_links_and_unexpected_members_fail(self):
        row = ('Shared/fpga/original.bit', self.body, tarfile.REGTYPE)
        for rows in ([row, row], [('Shared/fpga/original.bit', b'', tarfile.SYMTYPE)],
                     [('Shared/fpga/original.bit', b'', tarfile.LNKTYPE)],
                     [row, ('Shared/fpga/extra.bit', b'extra', tarfile.REGTYPE)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                module.gather(archive(rows), self.expected)

    def test_missing_size_and_same_size_wrong_contents_fail(self):
        for rows in ([], [('Shared/fpga/original.bit', b'x', tarfile.REGTYPE)],
                     [('Shared/fpga/original.bit', b'x' * len(self.body), tarfile.REGTYPE)]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                module.gather(archive(rows), self.expected)

    def test_flat_names_reject_traversal_and_nested_paths(self):
        for name in ('', '.', '..', '../file', '/file', 'nested/file', 'bad\0name'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                module.leaf(name)

    def test_index_requires_the_full_61_regular_member_cohort(self):
        rows = [{'name': 'Shared/fpga/' + str(i) + '.bit', 'kind': '0',
                 'size': 1, 'sha256': 'a' * 64} for i in range(61)]
        value = {'schema': 'ccrelay.shared_archive_contents.v1', 'verified': True, 'rows': rows}
        self.assertEqual(len(module.expected_files(value)), 61)
        for changed in (rows[:-1], rows + [rows[0]], [dict(rows[0], kind='2')] + rows[1:],
                        [dict(rows[0], sha256='invalid')] + rows[1:]):
            with self.subTest(rows=changed), self.assertRaises(ValueError):
                module.expected_files(dict(value, rows=changed))


if __name__ == '__main__':
    unittest.main()

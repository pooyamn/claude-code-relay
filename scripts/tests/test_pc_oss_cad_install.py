import importlib.util
from pathlib import Path
import tarfile
import unittest

spec = importlib.util.spec_from_file_location('oss_install', Path(__file__).resolve().parents[1] / 'install_pc_oss_cad.py')
installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)


class OssCadMembers(unittest.TestCase):
    def entry(self, name, kind=tarfile.REGTYPE, link=''):
        entry = tarfile.TarInfo(name); entry.type = kind; entry.linkname = link; entry.size = 1 if kind == tarfile.REGTYPE else 0
        return entry

    def test_regular_directory_and_contained_symlink(self):
        entries = [self.entry('oss-cad-suite', tarfile.DIRTYPE), self.entry('oss-cad-suite/libexec/openocd'),
                   self.entry('oss-cad-suite/bin/debug', tarfile.SYMTYPE, '../libexec/openocd')]
        self.assertEqual(installer.validate_members(entries)['unpackedFileBytes'], 1)

    def test_unsafe_names_and_duplicate_members_fail(self):
        for name in ['/oss-cad-suite/out', '../outside', 'oss-cad-suite/../out', 'oss-cad-suite//out', 'other/file', 'oss-cad-suite/out\n']:
            with self.assertRaises(ValueError): installer.validate_members([self.entry(name)])
        entry = self.entry('oss-cad-suite/file')
        with self.assertRaises(ValueError): installer.validate_members([entry, entry])

    def test_escaping_links_and_special_files_fail(self):
        for kind, target in [(tarfile.SYMTYPE, '/etc/passwd'), (tarfile.SYMTYPE, '../../outside'),
                             (tarfile.LNKTYPE, 'outside'), (tarfile.CHRTYPE, '')]:
            with self.assertRaises(ValueError): installer.validate_members([self.entry('oss-cad-suite/bin/file', kind, target)])
        installer.validate_members([self.entry('oss-cad-suite/lib/file', tarfile.LNKTYPE, 'oss-cad-suite/lib/original')])

    def test_member_size_and_total_bound(self):
        entry = self.entry('oss-cad-suite/huge'); entry.size = 512 * 1024 * 1024 + 1
        with self.assertRaises(ValueError): installer.validate_members([entry])
        with self.assertRaises(ValueError): installer.validate_members([])


if __name__ == '__main__': unittest.main()

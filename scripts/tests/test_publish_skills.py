import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('publish_skills', Path(__file__).resolve().parents[1] / 'publish_skills.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class PublishSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.skill = self.make_skill(self.source)
        self.consumers = [self.root / '.agents/skills', self.root / '.claude/skills']

    def make_skill(self, root, name='shared-example', text='One source'):
        skill = root / name
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text(f'---\nname: {name}\ndescription: Example workflow.\n---\n{text}\n')
        (skill / 'references').mkdir()
        (skill / 'references/guide.md').write_text('Shared supporting resource')
        return skill

    def groups(self):
        return [('personal', publisher.inventory([self.source]), self.consumers)]

    def test_dry_run_does_not_mutate(self):
        actions = publisher.plan(self.groups())
        self.assertEqual([a[1] for a in actions], ['link', 'link'])
        self.assertFalse(self.consumers[0].exists())

    def test_both_consumers_share_source_and_future_edits(self):
        publisher.apply(publisher.plan(self.groups()), self.root / 'backups')
        (self.skill / 'references/guide.md').write_text('Updated once')
        for root in self.consumers:
            self.assertEqual((root / self.skill.name).resolve(), self.skill)
            self.assertEqual((root / self.skill.name / 'references/guide.md').read_text(), 'Updated once')
        self.assertTrue(all(a[1] == 'ready' for a in publisher.plan(self.groups())))

    def test_future_skill_and_unmanaged_builtins_preserved(self):
        publisher.apply(publisher.plan(self.groups()), self.root / 'backups')
        unmanaged = self.consumers[0] / '.system'
        unmanaged.mkdir()
        (unmanaged / 'marker').write_text('vendor-owned')
        self.make_skill(self.source, 'another-skill')
        publisher.apply(publisher.plan(self.groups()), self.root / 'backups')
        self.assertTrue((self.consumers[1] / 'another-skill/SKILL.md').is_file())
        self.assertEqual((unmanaged / 'marker').read_text(), 'vendor-owned')

    def test_divergent_collision_prevents_all_writes(self):
        self.make_skill(self.consumers[1], text='Different user work')
        with self.assertRaises(publisher.Conflict):
            publisher.plan(self.groups(), deduplicate=True)
        self.assertFalse(self.consumers[0].exists())
        self.assertIn('Different user work', (self.consumers[1] / self.skill.name / 'SKILL.md').read_text())

    def test_wrong_and_broken_links_preserved(self):
        self.consumers[0].mkdir(parents=True)
        wrong = self.consumers[0] / self.skill.name
        wrong.symlink_to(self.root / 'missing')
        with self.assertRaises(publisher.Conflict):
            publisher.plan(self.groups())
        self.assertTrue(wrong.is_symlink())

    def test_identical_copy_needs_opt_in_and_is_recoverable(self):
        duplicate = self.make_skill(self.consumers[0])
        with self.assertRaises(publisher.Conflict):
            publisher.plan(self.groups())
        backups = publisher.apply(publisher.plan(self.groups(), deduplicate=True), self.root / 'backups')
        self.assertEqual(len(backups), 1)
        saved = Path(backups[0])
        self.assertEqual(publisher.fingerprint(saved / 'original'), publisher.fingerprint(self.skill))
        self.assertEqual(json.loads((saved / 'restore.json').read_text())['destination'], str(duplicate))
        self.assertTrue(duplicate.is_symlink())

    def test_copy_changed_after_preflight_is_not_moved(self):
        duplicate = self.make_skill(self.consumers[0])
        actions = publisher.plan(self.groups(), deduplicate=True)
        (duplicate / 'SKILL.md').write_text('Concurrent edit')
        with self.assertRaises(publisher.Conflict):
            publisher.apply(actions, self.root / 'backups')
        self.assertFalse(duplicate.is_symlink())
        self.assertEqual((duplicate / 'SKILL.md').read_text(), 'Concurrent edit')

    def test_conflicting_sources_rejected(self):
        second = self.root / 'second'
        self.make_skill(second, text='Another source')
        with self.assertRaises(publisher.Conflict):
            publisher.inventory([self.source, second])

    def test_project_scope_does_not_become_personal(self):
        personal = self.groups()
        project_source = self.root / 'project-source'
        self.make_skill(project_source, 'project-only')
        project_dest = self.root / 'project/.agents/skills'
        groups = personal + [('project', publisher.inventory([project_source]), [project_dest])]
        publisher.apply(publisher.plan(groups), self.root / 'backups')
        self.assertTrue((project_dest / 'project-only/SKILL.md').is_file())
        self.assertFalse((self.consumers[0] / 'project-only').exists())

    def test_fresh_mirror_includes_resources_and_hashes(self):
        mirror = self.root / 'mirror'
        result = publisher.export_mirror(publisher.inventory([self.source]), mirror)
        self.assertEqual(publisher.fingerprint(self.skill), publisher.fingerprint(mirror / self.skill.name))
        self.assertIn('references/guide.md', result[self.skill.name])
        self.assertEqual(json.loads((mirror / '.publish.json').read_text())['skills'], result)
        with self.assertRaises(publisher.Conflict):
            publisher.export_mirror(publisher.inventory([self.source]), mirror)

    def test_mirror_refuses_external_resource_links(self):
        (self.skill / 'outside').symlink_to(self.root / 'outside')
        with self.assertRaises(publisher.Conflict):
            publisher.export_mirror(publisher.inventory([self.source]), self.root / 'mirror')
        self.assertFalse((self.root / 'mirror').exists())

    def test_windows_mirror_does_not_require_posix_metadata_writes(self):
        with patch('shutil.copystat', side_effect=PermissionError('DrvFS metadata denied')):
            publisher.export_mirror(publisher.inventory([self.source]), self.root / 'mirror')
        self.assertEqual((self.root / 'mirror/shared-example/SKILL.md').read_bytes(), (self.skill / 'SKILL.md').read_bytes())


if __name__ == '__main__':
    unittest.main()

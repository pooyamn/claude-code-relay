#!/usr/bin/env python3
"""Publish declared custom skill sources to both tools without overwriting drift.

No recursive home scan, vendor-cache edits, credentials, model or network calls.
Check is the default. New skills in declared sources are included on each run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


class Conflict(ValueError):
    pass


def fingerprint(root, modes=True):
    """Compare the whole skill, including scripts/references/assets and modes."""
    entries = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries[relative] = ['link', os.readlink(path)]
        elif path.is_file():
            entries[relative] = ['file', hashlib.sha256(path.read_bytes()).hexdigest()]
            if modes:
                entries[relative].append(path.stat().st_mode & 0o777)
        elif path.is_dir():
            entries[relative] = ['directory']
        else:
            raise Conflict('Unsupported skill file: ' + str(path))
    return entries


def inventory(sources):
    result = {}
    for source in sources:
        if not source.is_dir():
            raise Conflict('Missing declared skill source: ' + str(source))
        for entry in sorted(source.iterdir()):
            if entry.name.startswith('.') or not (entry / 'SKILL.md').is_file():
                continue
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', entry.name) or entry.name == 'synced':
                raise Conflict('Invalid or reserved skill folder: ' + str(entry))
            target = entry.resolve(strict=True)
            if entry.name in result and result[entry.name] != target:
                raise Conflict('Conflicting skill sources: ' + entry.name)
            result[entry.name] = target
    return result


def load_groups(manifest, values):
    config = json.loads(manifest.read_text())
    if config.get('version') != 1:
        raise Conflict('Unsupported skills layout')
    groups = []
    for group in config['groups']:
        sources = [Path(p.format(**values)) for p in group['sources']]
        destinations = [Path(p.format(**values)) for p in group['destinations']]
        groups.append((group['scope'], inventory(sources), destinations))
    return groups


def plan(groups, deduplicate=False):
    actions = []
    seen = {}
    for scope, skills, destinations in groups:
        for root in destinations:
            # Don't publish through an unexpected redirected consumer root.
            if root.is_symlink() or root.exists() and not root.is_dir():
                raise Conflict('Redirected or non-directory skill root: ' + str(root))
            for name, source in skills.items():
                destination = root / name
                if destination in seen:
                    if seen[destination] != source:
                        raise Conflict('Conflicting destination: ' + str(destination))
                    continue
                seen[destination] = source
                if destination.is_symlink():
                    if destination.resolve() != source:
                        raise Conflict('Existing skill link points elsewhere: ' + str(destination))
                    state = 'ready'
                elif destination.exists():
                    if destination.resolve() == source:
                        state = 'ready'
                    elif deduplicate and destination.is_dir() and fingerprint(destination) == fingerprint(source):
                        state = 'backup-identical-copy'
                    else:
                        raise Conflict('Existing skill content preserved; resolve collision: ' + str(destination))
                else:
                    state = 'link'
                actions.append((scope, state, source, destination))
    return actions


def apply(actions, backup_root):
    backups = []
    for _, state, source, destination in actions:
        if state == 'ready':
            continue
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if state == 'backup-identical-copy':
            # Recheck immediately before moving; never overwrite divergent work.
            if destination.is_symlink() or fingerprint(destination) != fingerprint(source):
                raise Conflict('Skill changed during publication: ' + str(destination))
            backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            snapshot = Path(tempfile.mkdtemp(prefix=destination.name + '-', dir=backup_root))
            saved = snapshot / 'original'
            (snapshot / 'restore.json').write_text(json.dumps({'destination': str(destination), 'source': str(source)}))
            destination.rename(saved)
            try:
                destination.symlink_to(os.path.relpath(source, destination.parent), target_is_directory=True)
            except BaseException:
                saved.rename(destination)
                raise
            backups.append(str(snapshot))
        else:
            # symlink_to fails if anything appeared since preflight; no overwrite.
            destination.symlink_to(os.path.relpath(source, destination.parent), target_is_directory=True)
        if destination.resolve() != source or not (destination / 'SKILL.md').is_file():
            raise Conflict('Published skill unreadable: ' + str(destination))
    return backups


def export_mirror(skills, mirror):
    """Fresh generated Windows mirror; never merge into an existing directory."""
    if mirror.exists() or mirror.is_symlink():
        raise Conflict('Use a fresh mirror generation, existing content preserved')
    # Refuse external links in copied skill resources, not just the manifest.
    for source in skills.values():
        for path in source.rglob('*'):
            if path.is_symlink():
                raise Conflict('Mirror needs review of resource symlink: ' + str(path))
    mirror.mkdir(parents=True, mode=0o700)
    published = {}
    for name, source in skills.items():
        before = fingerprint(source, modes=False)
        target = mirror / name
        target.mkdir()
        # DrvFS may deny POSIX chmod/utime; native Windows needs byte identity,
        # not copied Unix metadata. Leave destination ACLs to the owning account.
        for path in sorted(source.rglob('*')):
            destination = target / path.relative_to(source)
            if path.is_dir():
                destination.mkdir()
            elif path.is_file():
                shutil.copyfile(path, destination)
            else:
                raise Conflict('Unsupported mirror resource: ' + str(path))
        if before != fingerprint(source, modes=False) or before != fingerprint(mirror / name, modes=False):
            raise Conflict('Source changed or mirror differs: ' + name)
        published[name] = {path: info[1] for path, info in before.items() if info[0] == 'file'}
    (mirror / '.publish.json').write_text(json.dumps({'version': 1, 'skills': published}, indent=2))
    return published


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path(__file__).with_name('skills-layout.json'))
    parser.add_argument('--owner-home', type=Path, default=Path.home())
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--deduplicate-identical', action='store_true')
    parser.add_argument('--mirror', type=Path, help='Export personal skills to a fresh generation for native Windows')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    workspace = args.workspace or args.owner_home / '.openclaw/workspace'
    groups = load_groups(args.manifest, dict(repo=str(repo), home=str(args.owner_home), workspace=str(workspace)))
    actions = plan(groups, args.deduplicate_identical)
    result = {'checked': len(actions), 'missing': sum(a[1] != 'ready' for a in actions), 'applied': False}
    if args.apply:
        result['backups'] = apply(actions, args.owner_home / '.local/share/agent-skills/backups')
        result['applied'] = True
        if args.mirror:
            personal = next(skills for scope, skills, _ in groups if scope == 'personal')
            result['mirrored'] = len(export_mirror(personal, args.mirror))
        result['missing'] = sum(a[1] != 'ready' for a in plan(groups))
    elif args.mirror:
        parser.error('--mirror requires --apply')
    print(json.dumps(result))
    return 0 if result['missing'] == 0 else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Conflict, OSError, ValueError) as error:
        print(json.dumps({'error': str(error), 'existing_content_preserved': True}))
        raise SystemExit(2)

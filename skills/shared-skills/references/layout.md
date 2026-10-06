# Shared skill layout

Canonical repository: `/Users/pouya/.openclaw/workspace/claude-code-relay`.
The live PC WSL home deliberately retains `/Users/pouya`; it is not a Mac-only
path. Native Windows uses `C:\Users\pou`.

## Sources and scope

`scripts/skills-layout.json` declares source roots and consumer roots. Every
immediate skill folder containing `SKILL.md` in those sources is published on
each run. Adding a new skill there does not require another catalog entry.
Register a new project explicitly; do not recursively activate research copies,
fixtures, downloaded plugins or backups found elsewhere in the home.

- Personal: relay `skills/` and workspace `skills/` → both personal discovery roots.
- Relay project: relay `skills/` → project `.agents/skills` and `.claude/skills`.
- ai-hil: existing `.claude/skills` remains source → `.agents/skills`.
- augur-1 and DUT-A: existing `.agents/skills` remains source → `.claude/skills`.
- kicad-happy: only its already-admitted `.agents/skills` entries are shared to
  `.claude/skills`; upstream source/plugin files and MCP configuration are unchanged.

The publisher follows the declared source's actual target and installs per-skill
relative symlinks on Linux. Existing unrelated entries are never pruned. Duplicate
files with different content, resource links or modes are conflicts, not an
invitation to choose the newer copy. Identical duplicates can be moved into
`<owner-home>/.local/share/agent-skills/backups/<generation>/original` with a
`restore.json` mapping; consumer links then share the retained source.

## Publish on WSL

From the canonical repository:

```sh
python3 scripts/publish_skills.py
python3 scripts/publish_skills.py --apply
```

Check exits 1 for missing links, 2 for a conflict, and 0 when all declared entries
are ready. For an intentionally approved consolidation of identical copies,
add `--deduplicate-identical`. No credentials or native actions are performed.

## Native Windows

Linux paths are not native Windows junction targets, and optional WSL UNC access
is not reliable enough for skill discovery. Export personal skills to a **fresh**
Windows-local generation using `--apply --mirror <fresh-/mnt/c/path>`; byte hashes
in `.publish.json` attest its scripts, references and assets. POSIX permissions
are not copied to DrvFS. The WSL sources remain authoritative.

Run a reviewed copy of `pc-router/publish-shared-skills.ps1` as ordinary Windows
`pou`, specifying `-Mirror <C:\...\generation> -Apply`. It publishes directory
junctions in that user's `.agents/skills`, `.codex/skills` and `.claude/skills`,
without replacing their roots, `.system`, synced skills or provider settings.

For a later export, pass the exact former generation as `-PreviousMirror`.
Only previously managed junctions to that generation, with unchanged old file
hashes, may be renewed. Original junctions and restore mappings are backed up;
the old mirror is retained. Divergent edits or foreign entries stay untouched.
This is explicit republishing, not a hidden background updater: republish native
Windows after changing a shared source. Run without `-Apply` afterward to verify
the installed generation. Do not edit the generated mirror directly.

## Verification limits

Verify whole-folder targets/resources, not just matching `SKILL.md` names.
Codex's existing daemon supports read-only `skills/list` with `forceReload:true`.
Claude's personal/project folders support symlinked skill folders and reload
changes, but an already-loaded skill's context is not retroactively rewritten.
Use `/reload-skills` if needed; do not restart busy model sessions merely to
publish a skill. Provider skills requiring special tools remain provider-owned.

Sources: [Codex discovery](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills),
[Claude discovery and reload](https://code.claude.com/docs/en/skills#choose-where-skills-load).

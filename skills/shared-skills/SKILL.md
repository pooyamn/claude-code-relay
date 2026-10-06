---
name: shared-skills
description: Create, update, publish or audit custom skills shared by native Claude Code and Codex, preserving project scope and provider-managed skills.
---

# Shared custom skills

Maintain one editable source per skill, with discovery links for both tools.
Read [references/layout.md](references/layout.md) for sources, publication and
Windows mirror renewal. Use your tool's skill-authoring guidance when available.

- Edit the canonical source, not a copied skill or generated consumer entry.
- Global custom skills live in the relay repository's `skills/` or the declared
  workspace `skills/`; project skills stay in their project. Do not promote a
  project-specific workflow to every session merely to share it between tools.
- Preserve `.system`, synced account skills, installed plugins and unrelated
  entries. They retain their provider/dependency owners; do not copy their caches
  into the other tool or assume its MCP/browser/runtime capabilities exist.
- Publish to Claude's `.claude/skills` and Codex's `.agents/skills`, retaining
  legacy `.codex/skills` compatibility for this pinned installation.
- Use `publish_skills.py` check, then apply; reject divergent name collisions.
  Consolidate identical copies only with the explicit deduplication option,
  retaining its backup and restore record.
- Both tools may read a runtime-specific skill without being able to execute it.
  Keep runtime and authorization boundaries in its trigger/instructions. Native
  Khadang topic requests must not invoke the retained Mac/tmux workflow.
- Validate the skill and supporting paths, check both discovery locations and
  native metadata where available. No model prompt, session restart or Telegram
  creation is needed just to test skill installation.

# Plan: group all relay sessions under one `relay` provider

**Status: READY, NOT APPLIED.** Prepared 2026-07-11 after the naive key-rename broke
routing (see CHANGELOG 0.5.1 "Reverted"). Do NOT rename model keys without the
registered backend below.

## Why the naive rename fails
The model picker groups by the key prefix (`anthropic/…`, `openai/…`), but the gateway
also **resolves which cliBackend to execute from that prefix** for relay models.
Only a **registered** backend (plugin/runtime registry) may declare `modelProvider`,
which is what creates a legitimate `provider ↔ runtime` binding (verified in
`dist/cli-backends-*.js`: `resolveCliBackendModelProvider`, `addCliRuntimeModelBinding`
— user-config `cliBackends` entries are NOT consulted for this). `anthropic/claude-*`
works because the anthropic extension calls `api.registerCliBackend` with
`{id: "claude-cli", modelProvider: "anthropic", …}` (see `dist/cli-backend-B0G5gyht.js`).

## Design (mirror the anthropic pattern)
1. **Plugin** (`openclaw-newcc-plugin/index.js`): in `register(api)`, call
   `api.registerCliBackend({ id: "cc-relay", modelProvider: "relay", config: {
     command: "<scripts>/cc-relay-dispatch", input: "arg", output: "text",
     sessionMode: "none", modelArg: "--relay-session" } })`.
   (Verify the exact descriptor schema against `buildAnthropicCliBackend()` in
   `dist/cli-backend-B0G5gyht.js` at implementation time — fields like `modelArg`,
   `args`, watchdog defaults.)
2. **Dispatcher** (`scripts/cc-relay-dispatch`, skeleton committed alongside this doc):
   receives `--relay-session <name>` + the composed message as last arg; maps `<name>`
   → `{folder, peer}` via `scripts/relay-map.json`; execs the existing
   `claude-tui-backend-multi <folder> <peer> <message>`. No other behavior change.
3. **Binder** (`bind-claude-code.py`): mint model key `relay/<slug>-<scope>` with value
   `{"agentRuntime": {"id": "cc-relay"}}`, write `<slug>-<scope> → {folder, peer}` into
   `relay-map.json`, and STOP writing per-session `cliBackends` entries.
4. **Migration**: for each existing binding, add its `relay-map.json` entry, flip the
   agents.list `model` to the new key, delete the old model key + per-session backend.

## Empirical unknowns to verify FIRST (in order)
- `api.registerCliBackend` descriptor schema (grep a current dist; it may drift).
- How `modelArg` composes with `input: "arg"` (does the model arrive as
  `--relay-session <name>` in argv before the message? test with a stub that logs argv).
- Whether provider id `relay` is accepted/normalized (not reserved).

## Staged rollout (non-negotiable after the 0.5.1 incident)
1. Patch plugin + add dispatcher; restart gateway. Registering an unused backend is
   inert — existing bindings untouched.
2. Create a SCRATCH topic; bind it via the NEW scheme only. Verify end-to-end
   (inbound → dispatcher argv correct → TUI answer → delivery; check the picker shows
   `relay` provider).
3. Migrate real bindings one at a time (ai-hil DM group last), gateway restart each.
4. Rollback at any point: restore old model key + per-session backend from the
   openclaw.json backup (binder makes one per run).

## Files
- `scripts/cc-relay-dispatch` — skeleton, committed, INERT until the plugin registers it.
- `scripts/relay-map.json` — created by the binder during migration.

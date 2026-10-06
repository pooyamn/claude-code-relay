# Existing Codex session enrollment on the PC

Use this after reading the skill entrypoint and obtaining a confirmed topic
creation receipt. The owner must have requested the binding. Existing recipe
scripts are **pinned historical releases**, not generic installers: inspect
current code/config/helper hashes, counts and native state before adapting one.

## Admission and artifacts

`RouterPolicy.ValidateBindings` checks the whole registry before native attach.
Linux launch independently checks literal directories, owner UID, trusted
ancestors, pinned native socket/executable, and actual OS denial of the protected
bot credential. Keep both checks.

The normal Linux root is `/Users/pouya/.openclaw/workspace`. The Android request
added only the literal `/Users/pouya/android router` exception for Codex with an
explicit Linux runtime. Adjacent directories, child-workspace admissions,
traversal, the entire home, and Claude admission are not implied. An ordinary
binding under the existing policy does not require another exception or build.

When a code/connector change is genuinely necessary:

- Review the smallest admission change and test denial cases as well as success.
- Build a self-contained Windows candidate from an isolated source copy.
  Changing `BaseIntermediateOutputPath` in a dirty source tree can cause old
  `obj` assembly files to be compiled twice. Do not remove the user's build tree.
- Run candidate Windows `--self-test` and relevant adapter tests before stopping
  production. Seal reviewed artifact copies under a fresh protected release.
- Copy the current hash-pinned Linux connector package into a new protected
  generation, changing only reviewed bytes. Keep the old package recoverable;
  preserve all unchanged configuration, participants, forums and Claude settings.
- If Windows UNC access to WSL is unavailable, stage through a fresh `/mnt/c`
  directory and read it as a local `C:\...` path. Do not change WSL permissions
  or restart the daemon merely to restore that optional share.

## Fence, snapshot and insert

`pc-router/deploy-kicad-topic.ps1` illustrates enrollment-only mechanics;
`pc-router/deploy-android-topic.ps1` illustrates enrollment with a narrow code
change. Do not run either's old fixed phase parameters for a different session.

1. Freshly inspect current routes and operation receipts. Require no uncertain
   native inputs, initial sends or pending answers. Claude and router-owned
   Windows sessions must be quiescent. A running independently supervised Linux
   Codex turn can remain active if the router has its exact durable turn receipt
   and recovery can re-adopt it without sending input. Preserve existing holds.
2. Save private pre-change state, startup-task XML, code/config/probe snapshots
   and exact registry payloads under Admin/SYSTEM protection. Import maintenance
   helpers only from reviewed, hash-checked protected files. Imported `Protect`
   requires `$admin`, `$system`, `$owner`; `Inspect` requires `$nativeRoot`.
3. Disable/stop `Oracova-KhadangStartup`, then stop **KhadangRouter only**. Do not
   stop WSL or the shared native Codex daemon. If Windows reports a stop error,
   observe actual service state before acting again; continue only on independently
   confirmed `Stopped` plus watchdog `Disabled`, not the command's return alone.
4. Acquire `state\exclusive.lock` before registry writes. Check operations and
   updates again under the lock. Use an SQLite `VACUUM INTO` snapshot of the
   existing database, then `BEGIN IMMEDIATE` for the single new binding. Reject
   duplicate chat/topic or thread IDs; never repoint an existing route silently.
5. Insert the payload with precisely these fields:

   ```json
   {"Chat":-1003550185469,"Topic":13750,"Name":"Android phone","Workspace":"/Users/pouya/android router","ThreadId":"01a104a5-c705-71b1-8614-c193d97da290","Backend":"codex","Runtime":"linux"}
   ```

   This is the verified Android example, **not defaults for another request**.
   Derive future values from that request's exact native observation and durable
   Telegram result. `Chat` must match the resolved source forum (or the owner's
   explicit alternate destination) and the creation receipt's `chat`; do not
   copy the example forum. Bindings are unique by chat/topic and by thread.
6. Compare all retained **SQLite payload strings byte-for-byte**, and verify the
   unrelated ledger digest before commit. PS5 native-command inspection can
   corrupt Unicode names; its display output is not authoritative for registry
   bytes. Use direct UTF-8 SQLite reads for snapshots/comparisons. Do not rewrite
   source names to match corrupted console output.

After an interrupted phase, inspect its receipts and actual state. Do not replay
creation, native input or an already committed insert. Leave uncertain effects
held and explain the evidence needed to reconcile them.

## Conditional fresh native proof

If code or protected configuration changed, the old `probe.json` no longer
matches. Stage reviewed bytes while stopped, run `--probe-service` through the
real SYSTEM service, and require fresh matching code/policy/owner/Windows sandbox,
Linux peer/workspace and credential-denial evidence. The generic probe does not
start a model turn or Telegram poller. Never simply update proof hashes.

Unchanged Claude acceptance may be carried forward only after comparing its
connector, native executable, input paths, policy and saved IDs; record the
limited reason, retain the fresh generic proof, and verify actual live reconnect.
Do not claim a new Claude test ran. If those components changed, existing
acceptance is insufficient.

For enrollment-only, preserve the already matching code/config proof; the
normal Linux connector must still attest the complete new workspace set.

## Activate and verify

Restore the normal `--service` command, start the router, and wait for fresh
status from the new process. Service `Running` alone is insufficient: status
is written after initialization and the first normal long poll, so an old
status file may temporarily show the prior route count.

Verify:

- Old routes/payloads unchanged, exactly one new route, and exact native ID/cwd.
- New bubble not held, with confirmed initial message ID if it is working;
  no unknown initial delivery or pending answer. Idle sessions may show Ready.
- Connected pre-existing Claude streams and the same shared Linux daemon PID
  and generation; the router-owned Windows stdio child normally gets a new PID.
- No native turn starts/steers or Claude user sends caused/replayed by enrollment;
  correlate exact receipts, not just a successful restart.
- Existing controller turn re-adopted and existing holds preserved.

Only then re-enable the startup watchdog. Retain reconciliation evidence for
uncertain edits of already-confirmed bubble IDs; those are different from an
unknown first send and do not justify duplicating the message.

The Android enrollment confirmed 14 routes, 7 connected Claude streams, shared
Linux PID 479 unchanged, 0 replayed inputs, and a delivered updating bubble in
topic 13750. No synthetic phone-to-model round trip was performed.

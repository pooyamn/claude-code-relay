# PC topic creation

The legacy Mac/tmux `ccrelay` catalog and native Claude peer nicknames are not
the live PC topic registry. A Claude topic cannot find the Codex controller by
searching only Claude peers. The shared topic-binding skill now uses the
token-free PC routing catalog and a verified native controller transport.

## Request path

From an enrolled Linux Claude or Codex project's cwd:

```sh
python3 /Users/pouya/.openclaw/workspace/claude-code-relay/scripts/pc_ccrelay_mcp.py list
python3 /Users/pouya/.openclaw/workspace/claude-code-relay/scripts/pc_ccrelay_mcp.py send \
  --to claude-code-relay --intent-id '<stable-human-request-key>' --text '<topic request>'
```

The same helper is configured as stdio MCP server `pc_ccrelay` in the owner's
Linux Claude and Codex user settings. Already-running sessions use the CLI;
they do not need to restart for tool discovery. MCP calls reload the routing
snapshot, including new child projects, instead of caching a parent identity.
The shared skill is published to both tools, including native Windows mirrors.
The verified requester transport here is Linux-only; Windows-native callers
are not silently substituted with a different project identity.

The adapter submits only to `claude-code-relay`; other aliases are metadata,
not authorized messaging targets. An active controller gets `turn/steer` with
its exact active turn ID. An idle loaded controller gets `turn/start` without
a resume. Unloaded, mismatched, ambiguous or unavailable targets fail closed.
No raw Claude peer-socket write is treated as model delivery. A measured socket
probe did not append to DUT's history and is retained as unconfirmed/submitted;
it must not be automatically replayed or released by loosening inbox policy.

The local SQLite message journal commits intent before delivery. Reusing a key
returns its previous receipt; changing its payload is refused. A crash, timeout
or uncertain acceptance never causes automatic input replay. Same-owner cwd
and alias selection are routing hints, **not authenticated company roles**.
Agent messages explicitly do not constitute human approval. The controller
checks the originating human request and protected source binding separately.

## Creation and enrollment

The request specifies source forum/topic, original human message reference,
requested name/project/backend, and `fresh` or `existing`. Only existing mode
requires an existing native session ID. The default destination is the source
forum, not the controller's forum. Default backend is the source backend.

Controller maintenance helpers must be reviewed, copied into Admin/SYSTEM-only
storage, hash-checked and executed through the existing elevated owner lane.
Ordinary requesters never receive Telegram credentials or registry authority.

- `create-codex-topic.ps1 -PreflightOnly` checks Khadang identity, forum admission
  and Manage Topics without creation. The historical filename also supports
  Claude UUIDs. Actual creation journals intent/result once; ambiguous create
  outcomes are not retried. Continue from the confirmed result.
- `enroll-fresh-claude-topic.ps1` retains a frozen plan, fences the router's
  watchdog, snapshots state and adds one exact binding/checkpoint. It preserves
  old SQLite payload bytes, pending/uncertain deliveries and existing holds.
  Independently supervised active Linux Codex sessions stay running. It starts
  exactly the new Claude UUID and existing project cwd, not a parent fork.
- Protected configuration changes require a fresh real SYSTEM native/ACL probe.
  Unchanged Claude binary/connector acceptance reuse is recorded explicitly;
  new live initialization must still succeed. Enrollment sends no model prompt.
- `announce-created-topic.ps1` posts only a verified creation result back in
  the originating topic, with a durable send receipt and no uncertain resend.
- `export-topic-catalog.ps1` exports fresh token-free live routes; publish it to
  `~/.config/ccrelay/pc-topics.json` after enrollment.

For detailed phase/recovery rules, read the shared
[`khadang-topic-binding` reference](../skills/khadang-topic-binding/references/pc-enrollment.md).
Do not run historical fixed-release deployment recipes with new parameters,
modify Hamal wiring, restart WSL/the shared Codex daemon, create another poller,
or silently grant more forum/project/employee authority.

## Acceptance, October 6

An owner-started CLI fixture from DUT's project resolved `duts` and delivered
`dut_x_controller_route_test_20261006` to this active Codex controller. Native
`turn/steer` acknowledged exact turn `01a11219-f2fb-7372-8777-fa7f17974a1e`;
the message appeared here as steering, not queued input or only a socket write.

The original owner request created DUT X in DUT's own forum:
[`DUT X`](https://t.me/c/4395661179/4901), chat `-1004395661179`, topic `4901`.
Its initial fresh Claude ID was `f0510c71-25f5-43de-accc-00a3dc5d8fbb`, cwd
`/Users/pouya/.openclaw/workspace/ai-hil/hardware/duts/dut-x`. At 17:04:43Z live
state showed 15 routes, 8 connected Claude streams, no uncertain inputs and
unchanged shared Linux Codex PID 479. A new actual SYSTEM probe confirmed native
owner, credential/code denial, Windows sandbox and Linux connection after the
single checkpoint configuration change; no router binary changed.

Before final verification, Pouya used `cc model cx` and sent DUT X its first
engineering task. Protected receipts show owner ID `110123423`, a committed
model switch and the accepted original message. Preserve that legitimate use:
the current Codex ID is `01a1122c-c62d-75f2-9b47-9ad9adcdf7d5`, same topic/cwd.
Final verification at 17:08:05Z preserved all 14 older routes and the shared
daemon, restored the watchdog, and recorded owner activity separately from
enrollment. Setup itself sent no native model input; this was not a synthetic
phone round-trip test. The strict verifier now understands omitted historical
Windows defaults and has an explicit, receipt-checked owner-activity option;
it never resets a topic merely because the owner began using it during setup.

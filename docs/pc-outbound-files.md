# PC Khadang outbound attachments

Native final answers can request a project file using a standalone line:

```
📎 /Users/pouya/.openclaw/workspace/project/diagram.png
📎 /Users/pouya/.openclaw/workspace/project/results.zip
```

Native Windows topics use their literal `C:\Users\pou\workspaces\...` path.
Both Claude and Codex share the same final-answer outbox. Markers are removed
from the clean prose; PNG/JPEG bytes use `sendPhoto`, other formats use
`sendDocument`. Local Markdown image embeds (`![Preview](/absolute/path.png)`)
also request uploads, and their placeholders are removed from the prose.
Fenced/inline code, escaped image syntax, remote image URLs and ordinary
Markdown file links do not upload.

The personal PC policy allows 16 files per final, each at most 20 MiB. This is
a local bound, not Telegram's document-upload maximum. Telegram documents
multipart uploads, a 10 MB photo limit and 50 MB document limit in its
[Bot API](https://core.telegram.org/bots/api#sending-files).

## Identity and delivery

- Bind the destination and source workspace to the protected topic registry.
  The answer cannot select a different chat, topic, URL or executable.
- Linux source reads are handled locally by the attested UID-1000 connector,
  not forwarded to a model/provider RPC and not opened by Windows SYSTEM.
  Literal project paths only; no-follow each directory/file, reject hardlinks,
  devices, writable-by-other files, credential/tool directories and oversize files.
  Root-owned CAD/container outputs are allowed only when the ordinary owner
  can read them; private root files and foreign-role ownership remain blocked.
- Each bounded chunk carries the same content hash. The assembled upload is
  independently verified. Retry after an explicit 429 must read the same hash.
- Windows source reads impersonate the verified non-elevated console owner,
  whose credential denial is checked first. Reparse paths are refused.
- Persist the per-file hash/size and unknown-send intent before HTTP. Confirm
  only an acknowledged Telegram message in the exact topic, retaining its ID
  and the operation's media receipt.
- Known read/upload failures produce a clean failure notice. A photo's explicit
  400 rejection can fall back to document; ambiguous timeout never falls back
  or resends. Confirmed files survive restart without duplication.
- Old already-delivered finals do not automatically acquire new uploads during
  upgrade. Repair historical missing files only from explicit owner authority,
  verified files, a one-time repair receipt, and a files-only durable outbox.

## DUT X incident, 2026-10-06

The shared file skill still promised the legacy upload behavior, but PC
`SendAnswer` only delivered text/rich text. The native final contained valid
`📎` PNG and ZIP paths; both files existed. Telegram's ledger contained zero
`sendPhoto`/`sendDocument` attempts. This was missing outbound implementation,
not a failed image generation, missing binding or Telegram photo rejection.

`deploy-outbound-files.ps1` preserves all session IDs, registry payloads,
delivered text and the existing Linux daemon. It enrolls only the owner's two
existing DUT X artifacts in a separate file outbox, with no repeated native
input or model prompt. Its verification requires actual photo/document receipts
in forum `-1004395661179`, topic `4901`, before declaring delivery complete.

Regression coverage includes standalone parsing/deduplication, file-only and
goal finals, durable intent before upload, confirmed restart deduplication,
known failures, explicit photo fallback, ambiguous timeout holds and rate-limit
retry. Linux tests exercise real bounded reads, mutation, symlinks, hardlinks,
outside-project paths, FIFOs and file-size limits without provider/model work.

Live verification at `2026-10-06T18:18:32Z`: PNG photo message **4922**
(198,005 source bytes), ZIP document message **4923** (1,809,574 bytes), all
15 routes retained, zero uncertain effects, Linux daemon PID 479 unchanged,
no native inputs submitted, and the original startup watchdog restored.
The DLL is `0c62d589b8051ddf10326e3319f0afdabdbf0be4b463030791bdbe7c5314e546`;
protected release `d486ecd6a1944a5a95536b1b5842d114` retains the prior binary,
config, registry, proof, test results and per-file receipts for rollback/audit.

Validation: 1,172 router checks on Linux, 1,175 on Windows (an initial
`JoinedTests` timing timeout passed on rerun), and 31 focused Python checks.
Fresh SYSTEM probes verified the actual ordinary-owner/credential/code
boundaries before live polling. Native Claude launch acceptance was explicitly
reused only for its unchanged connector and session pins; no model test was
invented or charged to subscriptions.

### Follow-up: native Markdown image and root-generated CAD output

The next DUT X final (text message 4929) used a local Markdown image embed,
not a `📎` line. The first implementation therefore created no file delivery.
Its new `dist/dut-x-reuse-pcb-3d.png` also had UID 0, mode 0644: the CAD
renderer produced a readable root-owned file, but the connector's strict
UID-1000 file-ownership check would have refused it.

The follow-up recognizes explicit local image embeds, preserving ordinary
links and code examples. The Linux reader accepts readable UID-0 project
outputs without elevating the reader or relaxing path/link/permission checks.
Read timeouts now become visible attachment failures, not editor-loop exits.
Regression tests cover the exact native final format, deduplication, durable
flush, root-generated outputs and private/foreign-owner denial. The deployment
recipe's `-RepairNativeImage` mode preserves the completed final and its text
receipt, and admits only this exact new PNG/hash to a separate files-only
outbox. It requires the new photo's own confirmed receipt; the older 4922/4923
receipts do not satisfy this verification.

The live response moved to a newer active Codex turn during Windows tests.
The first staging guard refused it before changing production state; the
original router and watchdog were restored. Historical repair now checks the
protected confirmed text receipt 4929 in the exact forum/topic, rather than
requiring the old final to remain the current response. The newer response,
turn ID, native inputs and all registry bindings remain intact.

Live verification at `2026-10-06T19:04:51Z`: the **new** PNG was confirmed as
photo message **4931** in topic **4901**, 133,607 source bytes, SHA-256
`91ba5a68dff10d4eb37c31a499b20ff65b4467319e95e5b78180e6396552f0cb`.
All 15 routes remained online, all seven Claude streams connected, zero
uncertain effects, daemon PID 479 unchanged, no native inputs submitted,
and the original startup watchdog restored. Protected release
`d061403e1aee44ff941038e1417f3fe0` retains the prior artifacts, registry
snapshot, fresh SYSTEM proof, tests and this image's own upload receipt.
The deployed DLL is
`ba3912e1528f90a7a6bb79f899355ab9677ee817db0dff3e104aa9cee7488bd9`.

Validation: 1,177 router checks on Linux, 1,180 on Windows, and 60 Python
artifact/native-connector checks. The shared file skill was republished to
Claude and Codex on Linux and native Windows; ordinary file links stay
references, explicit local image embeds request uploads, and delivery claims
still require actual receipts.

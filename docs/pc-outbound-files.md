# PC Khadang outbound attachments

Native final answers can request a project file using a standalone line:

```
📎 /Users/pouya/.openclaw/workspace/project/diagram.png
📎 /Users/pouya/.openclaw/workspace/project/results.zip
```

Native Windows topics use their literal `C:\Users\pou\workspaces\...` path.
Both Claude and Codex share the same final-answer outbox. Markers are removed
from the clean prose; PNG/JPEG bytes use `sendPhoto`, other formats use
`sendDocument`. Fenced examples and ordinary Markdown file links do not upload.

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

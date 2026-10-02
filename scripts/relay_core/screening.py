"""Pure masked Jev screening CONTRACT, not triage or a model/network client.

Never discovers environment/home credentials. The protected screener supplies
explicit known values and candidate-only bytes. Masking is defense in depth,
not a proof that arbitrary source contains no secret. Missing coverage holds
deployment or requires an exact, explicit owner exception.
"""
import base64
import hashlib
import re
from urllib.parse import quote

from .contracts import canonical_bytes, fingerprint
from .identity import Denied, exact


PATTERNS = (
    re.compile(r"\b\d{8,12}:AA[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}|AKIA[A-Z0-9]{16})\b"),
    re.compile(r"-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----.*?-----END (?:[A-Z ]*PRIVATE KEY)-----", re.DOTALL),
    re.compile(r"(?im)\b(?:password|secret|api[_-]?key|token|authorization)\s*[:=]\s*[^\r\n]+"),
)


def mask(text, known_secrets=()):
    if type(text) is not str:
        raise Denied("screening text required")
    values = set()
    for value in known_secrets:
        if type(value) is not str or len(value) < 4:
            raise Denied("invalid explicit masking value")
        values.update((value, quote(value, safe=""), value.encode().hex(), base64.b64encode(value.encode()).decode()))
    for value in sorted(values, key=len, reverse=True):
        text = text.replace(value, "[MASKED]")
    for pattern in PATTERNS:
        text = pattern.sub("[MASKED]", text)
    return text


def payload(manifest, contents, *, known_secrets=()):
    # contents are the VERIFIED immutable candidate, not caller-selected host
    # paths. Include dependencies/configuration, not just a textual diff.
    if set(contents) != {entry["path"] for entry in manifest["files"]}:
        raise Denied("incomplete candidate screening source")
    files, incomplete = [], []
    for entry in manifest["files"]:
        body = contents[entry["path"]]
        if type(body) is not bytes or len(body) != entry["size"] or "sha256:" + hashlib.sha256(body).hexdigest() != entry["digest"]:
            raise Denied("screening source differs from candidate artifact")
        try:
            text = body.decode("utf-8")
            if "\x00" in text:
                raise UnicodeError("binary source")
            files.append({"path": entry["path"], "text": mask(text, known_secrets)})
        except UnicodeError:
            incomplete.append(entry["path"])
    value = {"schema": "ccrelay.screening_payload.v1", "artifact_digest": fingerprint(manifest),
             "files": files, "incomplete_paths": incomplete}
    # Bound text before any future provider call. An oversized candidate is NOT
    # silently truncated into a purported complete security review.
    canonical_bytes(value)
    return value


def report(raw, manifest, masked_payload):
    exact(raw, {"schema", "artifact_digest", "payload_digest", "verdict", "evidence_id", "model", "coverage_complete"})
    if raw["schema"] != "ccrelay.screening_report.v1" or type(raw["verdict"]) is not str or \
            raw["verdict"] not in {"clear", "flagged", "unavailable", "uncertain", "incomplete"}:
        raise Denied("unsupported deployment screening report")
    if raw["artifact_digest"] != fingerprint(manifest) or raw["payload_digest"] != fingerprint(masked_payload):
        raise Denied("screening report binds another candidate or payload")
    if type(raw["coverage_complete"]) is not bool or raw["coverage_complete"] != (not masked_payload["incomplete_paths"]):
        raise Denied("screening coverage claim disagrees with source")
    if type(raw["evidence_id"]) is not str or not raw["evidence_id"] or type(raw["model"]) is not str or not raw["model"]:
        raise Denied("screening provenance/evidence required")
    if raw["verdict"] == "clear" and not raw["coverage_complete"]:
        raise Denied("incomplete screening cannot grant clearance")
    canonical_bytes(raw)
    return dict(raw)

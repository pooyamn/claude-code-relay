"""Join durable exact resume, settings epochs and captured independent observation.

No launch, discovery, new model turn or uncertain-action replay. The loaded-context
verifier and kernel/subscription/admission facts must come from a protected driver;
this composition does not establish them or enable a runtime entry point.
"""
from dataclasses import asdict

from .identity import Denied
from .native_epochs import NativeControlEpochs, NativeEpochTicket
from .native_observe import CodexNativeObserver
from .native_resume import CodexExactResume
from .native_rpc import CodexRPC
from .native_sessions import NativeSessionRegistry


ADAPTER = "codex-app-server-controlled-resume.v1"


class CodexControlledResume(CodexExactResume):
    adapter_id = ADAPTER

    def __init__(self, rpc, controls, observer, *, authorize, resume_supported):
        if type(rpc) is not CodexRPC or type(controls) is not NativeControlEpochs or \
                type(observer) is not CodexNativeObserver or observer.rpc is not rpc or observer.controls is not controls:
            raise Denied("exact captured RPC, epoch ledger and joined observer required")
        self.native_rpc, self.controls, self.observer = rpc, controls, observer
        super().__init__(rpc.rpc, response_evidence=rpc.response_evidence,
                         authorize=authorize, resume_supported=resume_supported)

    def _cohort(self, thread_id, worktree, settings_digest):
        cohort = self.controls._row(self.native_rpc.connection_id)
        self.controls._rpc(self.native_rpc, cohort)
        if cohort["state"] == "closed" or \
                (cohort["thread_id"], cohort["worktree"], cohort["settings_digest"]) != (thread_id, worktree, settings_digest):
            raise Denied("resume differs from current native control cohort")
        return cohort

    def _admit_control(self, action, row, ledger, registry):
        if type(registry) is not NativeSessionRegistry or registry.observe_runtime is not self.observer or \
                self.observer.rpc is not self.native_rpc or self.observer.controls is not self.controls or \
                not callable(self.observer.inspect_loaded_context) or \
                ledger.policy_digest != self.controls.policy_digest or registry.policy_digest != self.controls.policy_digest:
            raise Denied("current joined observer and common protected policy required")
        native = row["enrollment"]
        self._cohort(native["provider_session_id"], native["worktree"], action.fields["parameters"].get("settings_digest"))

    def _begin_control(self, plan):
        cohort = self._cohort(plan["parameters"]["threadId"], plan["parameters"]["cwd"], plan["target"]["settings_digest"])
        epoch = self.controls.invalidate(self.native_rpc, expected_epoch=cohort["epoch"], reason="native_resume_pending")
        # Pending ticket is scope only, NOT a current settings baseline.
        return NativeEpochTicket(cohort["connection_id"], cohort["source_digest"], epoch, cohort["settings_digest"])

    def _accept_control(self, plan, attempt_id, response, captured, pending):
        epoch = self.controls.accept_resume(self.native_rpc, expected_epoch=pending.epoch, request_id=attempt_id, response=response)
        ticket = self.controls.ticket(self.native_rpc)
        cohort = self.controls._row(ticket.connection_id)
        if ticket.epoch != epoch or (ticket.connection_id, ticket.source_digest, ticket.settings_digest) != \
                (pending.connection_id, pending.source_digest, pending.settings_digest) or cohort["baseline_reference"] != captured:
            raise Denied("resume baseline differs from this submitted attempt")
        return ticket

    def _validate_control(self, ticket):
        return asdict(self.controls.validate(self.native_rpc, ticket))

    def deliver(self, ledger, intent_id, attempt_id, registry, controller):
        result = super().deliver(ledger, intent_id, attempt_id, registry, controller)
        if result["state"] == "unknown":
            # A control change after observation cannot leave its cached ready
            # flag usable. Never overwrite a newer pause or revoked binding.
            try:
                action = ledger.load(intent_id)["record"]
                session_id = action.fields["parameters"]["session_id"]
                current = registry.cached(session_id)
                if current.fields["ready"] and current.fields["desired_state"] == "running":
                    registry.prepare_resume(controller, session_id, expected_revision=current.revision)
            except Denied:
                pass  # Current authority refuses mutation; no fallback grant.
        return result

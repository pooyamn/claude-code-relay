"""Synthetic source, all-source fence and quota facts; real joined SQLite state."""
from relay_core.contracts import fingerprint
from relay_core.model_admission import ActivityReceipt, ModelAdmission, PacingPolicy, QuotaReceipt, QuotaWindow, SourceReceipt, StopReceipt


def scheduler(fixture):
    now = lambda: fixture.clock[0]
    return ModelAdmission(fixture.ledger, PacingPolicy(100, 60000, 1000),
        verify_source=lambda scope: SourceReceipt(fingerprint(scope), fingerprint({"synthetic_source": True}),
                                                  scope["model_request"]["origin"], False, False),
        observe_activity=lambda scope: ActivityReceipt(fingerprint(scope), fingerprint({"synthetic_fence_not_kernel": True}), now(), (), True),
        observe_quota=lambda scope: QuotaReceipt(fingerprint(scope), fingerprint({"synthetic_quota_not_provider": True}),
            scope["model_request"]["provider"], scope["model_request"]["account_id"], scope["model_request"]["model_id"],
            now(), (QuotaWindow("window-1", "account", 100, 0, 1790966400000 + 100000, ()),), True),
        verify_stop=lambda row: StopReceipt(fingerprint(row), fingerprint({"synthetic_tools_not_real_stop": True}), True, True))


def request(key="turn-1", session="builder.task", *, account="shared-account", origin="telegram", estimate=10):
    return {"id": key, "session_id": session, "provider": "synthetic-native-provider", "account_id": account,
            "model_id": "fixture/model", "native_session_id": "fixture-native-" + session,
            "runtime_digest": fingerprint({"synthetic_runtime": True}), "adapter_digest": fingerprint({"synthetic_adapter": True}),
            "origin": origin, "estimated_units": {"window-1": estimate}}


def plan(ledger, action):
    binding = ledger.load(action.id)["context"]["binding"]
    params = ledger.load(action.id)["context"].get("model_request", action.to_dict()["parameters"])
    return {"schema": "ccrelay.delivery_plan.v1", "intent_id": action.id, "intent_digest": action.fields["intent_digest"],
            "adapter_id": "synthetic-model-adapter", "authorization_id": "synthetic-model-grant",
            "parameters": action.to_dict()["parameters"], "target": {"session_id": binding["session_id"], "binding_digest": fingerprint(binding),
                **{key: params[key] for key in ("provider", "account_id", "model_id", "native_session_id", "runtime_digest", "adapter_digest")}}}

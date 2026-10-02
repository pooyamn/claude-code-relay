"""Synthetic usage ceiling; never a real external-activity/quota observer."""
from relay_core.contracts import fingerprint
from relay_core.quota_estimates import EstimatePolicy, QuotaEstimates, UsageBoundReceipt


def estimates(admission, fixture, *, policy=None, reader=None):
    policy = policy or EstimatePolicy(90000, 1000, 2, 5000)  # Explicit fixture values only.
    reader = reader or (lambda scope: UsageBoundReceipt(fingerprint(scope), fingerprint({"synthetic_usage_not_native": True}),
        fingerprint(scope["anchor"]), fixture.clock[0], {key: 0 for key in scope["model_scope"]["model_request"]["estimated_units"]}, True))
    return QuotaEstimates(admission, policy, verify_usage_bound=reader)

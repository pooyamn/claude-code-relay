"""Actual process death around the LOCAL pointer effect, inside test sandbox."""
import os
from pathlib import Path
import sys
from unittest import mock

from relay_core.artifacts import BootstrapDeployer, DeploymentPolicy
import relay_core.artifacts as artifacts
from owner_fixtures import GATE, deployment_fields, open_ledger, open_store


def main():
    folder, boundary = Path(sys.argv[1]), sys.argv[2]
    scratch = Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()
    if not folder.resolve().is_relative_to(scratch):
        raise RuntimeError("crash fixture must be inside isolated scratch")
    ledger = open_ledger(folder / "ledger")
    store = open_store(folder / "artifacts")
    deployer = BootstrapDeployer(DeploymentPolicy(deployment_fields()), store, ledger)
    original_claim = ledger.claim
    original_replace = artifacts.os.replace

    def claim(*args, **kwargs):
        if boundary == "before_claim":
            os._exit(73)
        value = original_claim(*args, **kwargs)
        if boundary == "after_claim":
            os._exit(73)
        return value

    def replace(*args, **kwargs):
        original_replace(*args, **kwargs)
        if boundary == "after_pointer":
            os._exit(73)

    def confirm(*args, **kwargs):
        ledger.__class__.confirm(ledger, *args, **kwargs)
        os._exit(73)

    ledger.claim = claim
    if boundary == "after_confirm":
        ledger.confirm = confirm
    with mock.patch("relay_core.artifacts.protected_path", side_effect=lambda path, **_: Path(path)), \
            mock.patch("relay_core.artifacts.os.replace", side_effect=replace):
        deployer.activate(GATE, "action-1", "attempt-1")


if __name__ == "__main__":
    main()

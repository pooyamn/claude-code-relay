"""Actual scratch process death around registry commits, never a native agent."""
import os
from pathlib import Path
import sys

from native_session_fixtures import CONTROLLER, enrollment, native_fixture


def main():
    folder, boundary = Path(sys.argv[1]), sys.argv[2]
    if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or not folder.resolve().is_relative_to(
            Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()):
        raise RuntimeError("fixture must stay inside isolated scratch")
    def checkpoint(name):
        if name == boundary:
            os._exit(73)
    with native_fixture(folder, checkpoint=checkpoint) as (registry, authority):
        record = registry.enroll(CONTROLLER, enrollment())
        observed = registry.refresh(CONTROLLER, record.id, expected_revision=record.revision)
        if "desired" in boundary:
            registry.desired(CONTROLLER, record.id, "paused", expected_revision=observed.revision)
    raise AssertionError("configured process death did not occur")


if __name__ == "__main__":
    main()

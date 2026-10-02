"""Scratch-only broker registry revocation commit followed by actual death."""
import os
from pathlib import Path
import sys
from unittest import mock

from relay_core.bindings import BindingRegistry


folder = Path(sys.argv[1]).resolve()
if os.environ.get("CCRELAY_ISOLATED_TEST") != "1" or not folder.is_relative_to(Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()):
    raise RuntimeError("binding revocation death fixture must stay isolated")
with mock.patch("relay_core.bindings.protected_path", side_effect=lambda value, **_: Path(value)):
    registry = BindingRegistry(folder, owner_uid=os.geteuid())
registry.revoke("builder.fixture")
os._exit(75)

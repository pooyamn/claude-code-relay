"""Actual process-death goal fixture; source runs only in isolated scratch."""
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

from relay_codex_goal import GoalControl, GoalInbox, GoalView


def native_goal(**fields):
    return {"threadId": "native-1", "objective": "Finish the fixture", "status": "active",
            "tokensUsed": 57, "timeUsedSeconds": 30, "createdAt": 100, "updatedAt": 100,
            "tokenBudget": 8000, **fields}


def main():
    folder, phase = Path(sys.argv[1]), sys.argv[2]
    scratch = Path(os.environ["CCRELAY_TEST_SCRATCH"]).resolve()
    if not folder.resolve().is_relative_to(scratch):
        raise RuntimeError("goal fault fixture must be isolated")
    provider = sqlite3.connect(folder / "provider.sqlite")
    provider.execute("CREATE TABLE IF NOT EXISTS effects (body TEXT NOT NULL)")
    provider.commit()
    def rpc(method, params):
        if method == "thread/goal/get":
            return {"result": {"goal": native_goal()}}
        if phase == "before-write":
            os._exit(71)
        with provider:
            provider.execute("INSERT INTO effects VALUES (?)", (json.dumps(params),))
        if phase == "after-write":
            os._exit(71)
        return {"result": {"goal": native_goal(status=params["status"])}}
    view = GoalView("native-1")
    control = GoalControl(view, rpc)
    class ExitAfterResult:
        def execute(self, command):
            result = control.execute(command)
            if phase == "after-result":
                os._exit(71)
            return result
    conn = SimpleNamespace(tid="native-1", goal_view=view, goal_control=ExitAfterResult())
    inbox = GoalInbox(folder, "fixture-key")
    inbox.run_one(conn, "native-1")
    inbox.close()
    provider.close()


if __name__ == "__main__":
    main()

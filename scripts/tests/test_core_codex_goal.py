"""Offline goal contracts, joined routing/UI and real scratch process deaths."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import ccrelayd
from goal_fault_fixture import native_goal
from relay_codex_bubble import BubblePages, BubbleState, install
from relay_codex_goal import GoalControl, GoalInbox, GoalView, parse_command
from relay_tg import _split_for_html, md_to_html


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.goal = native_goal()
        self.view = GoalView("native-1")
        self.calls = []
        self.control = GoalControl(self.view, self.rpc)

    def rpc(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "thread/goal/get":
            return {"result": {"goal": copy.deepcopy(self.goal)}}
        if method == "thread/goal/clear":
            self.goal = None
            return {"result": {}}
        self.goal = {**(self.goal or native_goal()), **params}
        return {"result": {"goal": copy.deepcopy(self.goal)}}

    def test_command_aliases_preserve_objective_case(self):
        for text in ("/goal Fix PB15", "cc goal Fix PB15", "/cc goal set Fix PB15", "/GOAL@SyntheticKhadang Fix PB15"):
            self.assertEqual(parse_command(text), {"action": "set", "objective": "Fix PB15"})
        for text in ("/goal", "/goal status", "cc goal STATUS"):
            self.assertEqual(parse_command(text), {"action": "status"})
        for action in ("pause", "resume", "clear"):
            self.assertEqual(parse_command("cc goal " + action), {"action": action})

    def test_quoted_commands_and_ordinary_prose_are_not_controls(self):
        for text in ('Please /goal pause', '“/goal resume”', '> /goal clear', 'ongoing goal', '/goalkeeper pause',
                     'Goal command in codex is very useful\nLets add that feature support', 'goal needs your review'):
            self.assertIsNone(parse_command(text))

    def test_empty_set_and_oversize_objective_rejected_without_inference(self):
        for text in ("/goal set", "/goal " + "x" * 4001):
            with self.assertRaises(ValueError):
                parse_command(text)
        self.assertEqual(len(parse_command("/goal " + "x" * 4000)["objective"]), 4000)

    def test_pause_and_resume_omit_objective_and_budget_preserving_usage(self):
        for action, status in (("pause", "paused"), ("resume", "active")):
            state, notice = self.control.execute({"action": action})
            self.assertEqual(state, "confirmed")
            self.assertEqual(self.calls[-1], ("thread/goal/set", {"threadId": "native-1", "status": status}))
            for key in ("tokensUsed", "timeUsedSeconds", "createdAt", "tokenBudget"):
                self.assertEqual(self.goal[key], native_goal()[key])
            if action == "pause":
                self.assertIn("current turn was not interrupted", notice)

    def test_set_and_clear_use_real_native_methods_not_turn_start(self):
        self.assertEqual(self.control.execute({"action": "set", "objective": "New explicit goal"})[0], "confirmed")
        self.assertEqual(self.calls[-1], ("thread/goal/set", {"threadId": "native-1", "objective": "New explicit goal", "status": "active"}))
        self.assertEqual(self.control.execute({"action": "clear"})[0], "confirmed")
        self.assertIn(("thread/goal/clear", {"threadId": "native-1"}), self.calls)
        self.assertEqual(self.view.line(), "")
        self.assertFalse(any(method.startswith("turn/") for method, _ in self.calls))

    def test_missing_or_complete_goal_cannot_be_accidentally_recreated_on_resume(self):
        for goal in (None, native_goal(status="complete")):
            self.goal, self.calls = goal, []
            self.assertEqual(self.control.execute({"action": "resume"})[0], "rejected")
            self.assertEqual([m for m, p in self.calls], ["thread/goal/get"])

    def test_budget_and_usage_limited_status_are_displayed_not_claimed_working(self):
        for status, label in (("budgetLimited", "budget limited"), ("usageLimited", "usage limited"), ("blocked", "blocked")):
            self.view.apply(native_goal(status=status), "native-1")
            self.assertIn(label, self.view.line())

    def test_foreign_or_unscoped_goal_event_cannot_leak_or_alter_display(self):
        self.view.apply(self.goal, "native-1")
        for thread in ("foreign", None):
            self.assertFalse(self.view.observe({"method": "thread/goal/updated", "params": {"threadId": thread, "goal": native_goal(threadId=thread, objective="Private foreign goal")}}))
            self.assertFalse(self.view.observe({"method": "thread/goal/cleared", "params": {"threadId": thread}}))
        self.assertNotIn("foreign", self.view.line())

    def test_goal_notifications_need_no_turn_id_and_follow_native_clear(self):
        self.assertTrue(self.view.observe({"method": "thread/goal/updated", "params": {"threadId": "native-1", "goal": self.goal}}))
        self.assertIn("Goal: active", self.view.line())
        self.assertTrue(self.view.observe({"method": "thread/goal/cleared", "params": {"threadId": "native-1"}}))
        self.assertEqual(self.view.line(), "")

    def test_slow_read_cannot_overwrite_newer_notification(self):
        def rpc(method, params):
            self.view.observe({"method": "thread/goal/updated", "params": {"threadId": "native-1", "goal": native_goal(status="paused")}})
            return {"result": {"goal": native_goal(status="active")}}
        GoalControl(self.view, rpc).read()
        self.assertIn("Goal: paused", self.view.line())

    def test_newer_complete_notification_prevents_resume_after_slow_active_read(self):
        def rpc(method, params):
            self.calls.append(method)
            self.view.observe({"method": "thread/goal/updated", "params": {"threadId": "native-1", "goal": native_goal(status="complete")}})
            return {"result": {"goal": native_goal(status="active")}}
        self.assertEqual(GoalControl(self.view, rpc).execute({"action": "resume"})[0], "rejected")
        self.assertEqual(self.calls, ["thread/goal/get"])

    def test_failed_missing_or_broken_read_does_not_publish_cached_active_as_current(self):
        for response in (None, {"result": {}}, {"result": None}):
            self.view.apply(native_goal(), "native-1")
            self.control.rpc = lambda *_, response=response: response
            self.assertEqual(self.control.execute({"action": "pause"})[0], "rejected")
            self.assertNotIn("Goal: active", self.view.line())
        self.view.apply(native_goal(), "native-1")
        self.control.rpc = mock.Mock(side_effect=OSError("Fixture disconnected"))
        self.assertEqual(self.control.execute({"action": "pause"})[0], "rejected")
        self.assertIn("unavailable", self.view.line())

    def test_slow_write_ack_cannot_overwrite_newer_notification_even_same_timestamp(self):
        original = self.control.rpc
        def rpc(method, params):
            if method == "thread/goal/set":
                self.view.observe({"method": "thread/goal/updated", "params": {"threadId": "native-1", "goal": native_goal(status="paused")}})
                return {"result": {"goal": native_goal(status="active")}}
            return original(method, params)
        self.control.rpc = rpc
        self.control.execute({"action": "resume"})
        self.assertIn("Goal: paused", self.view.line())

    def test_rebinding_during_read_cannot_mutate_new_thread(self):
        def rpc(method, params):
            self.calls.append(method)
            self.view.bind("replacement")
            return {"result": {"goal": native_goal()}}
        self.assertEqual(GoalControl(self.view, rpc).execute({"action": "pause"})[0], "rejected")
        self.assertEqual(self.calls, ["thread/goal/get"])
        self.assertNotIn("Finish the fixture", self.view.line())

    def test_invalid_accounting_and_cross_thread_read_are_rejected(self):
        for goal in (native_goal(threadId="foreign"), native_goal(tokensUsed=True), native_goal(tokenBudget=0), native_goal(status="madeUp")):
            self.control.rpc = lambda *_, goal=goal: {"result": {"goal": goal}}
            self.assertEqual(self.control.execute({"action": "pause"})[0], "rejected")
        self.assertIn("unavailable", self.view.line())

    def test_unsupported_native_method_never_falls_back_to_model_prompt(self):
        self.control.rpc = lambda *args: {"error": {"code": -32601, "message": "Method not found"}}
        state, text = self.control.execute({"action": "set", "objective": "Fixture"})
        self.assertEqual(state, "rejected")
        self.assertIn("-32601", text)
        self.assertIn("Method not found", text)

    def test_lost_write_reply_is_unknown_and_native_error_remains_rejected(self):
        original = self.control.rpc
        self.control.rpc = lambda m, p: original(m, p) if m.endswith("get") else None
        state, text = self.control.execute({"action": "pause"})
        self.assertEqual(state, "unknown")
        self.assertIn("not retried", text)
        self.assertIn("unavailable", self.view.line())
        self.control.rpc = lambda m, p: original(m, p) if m.endswith("get") else {"error": {"code": -1, "message": "TOKEN=synthetic-secret permission denied"}}
        state, text = self.control.execute({"action": "pause"})
        self.assertEqual(state, "rejected")
        self.assertIn("permission denied", text)
        self.assertNotIn("synthetic-secret", text)

    def test_ack_with_wrong_requested_status_does_not_claim_successful_pause(self):
        self.control.rpc = lambda *_: {"result": {"goal": native_goal(status="active")}}
        state, text = self.control.execute({"action": "pause"})
        self.assertEqual(state, "unknown")
        self.assertNotIn("Pause acknowledged", text)
        self.assertIn("requested state was not returned", text)

    def test_redacted_literal_objective_footer_fits_one_message_below_timer(self):
        self.view.apply(native_goal(objective="TOKEN=synthetic-secret ```\n[click](https://example.invalid) " + "😀" * 2000), "native-1")
        line = self.view.line()
        self.assertNotIn("synthetic-secret", line)
        with tempfile.TemporaryDirectory() as directory:
            sends, edits = [], []
            state = BubbleState(directory, "native-1", "turn-1", "-100", "53")
            pages = BubblePages(state, lambda text: sends.append(text) or "123", lambda mid, text: edits.append((mid, text)) or True,
                                _split_for_html, rolling=True, clock=lambda: 0)
            for text in ("😀" * 20000 + "NEW", "&" * 20000 + "NEW", "```\n" + "x" * 20000 + "NEW"):
                pages.update(text, force=True, goal_line=line)
            rendered = edits[-1][1]
            self.assertEqual(len(sends), 1)
            self.assertEqual({mid for mid, text in edits}, {"123"})
            self.assertIn("NEW", rendered)
            self.assertLessEqual(len(md_to_html(rendered).encode("utf-16-le")) // 2, 3900)
            self.assertTrue(rendered.splitlines()[-2].startswith("Working ("))
            self.assertTrue(rendered.splitlines()[-1].startswith("Goal: active"))

    def test_bad_overlarge_footer_is_rejected_without_an_infinite_trim_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            pages = BubblePages(BubbleState(directory, "native-1", "turn-1", "-100", "53"),
                                mock.Mock(), mock.Mock(), _split_for_html, rolling=True)
            with self.assertRaises(ValueError):
                pages.rolling_text("latest", "inProgress", "Goal: " + "😀" * 5000)


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.inbox = GoalInbox(self.folder, "fixture-key")
        self.addCleanup(lambda: self.inbox.close())
        self.calls = []
        self.conn = SimpleNamespace(tid="native-1", goal_view=GoalView("native-1"),
            goal_control=SimpleNamespace(execute=lambda c: self.calls.append(c) or ("confirmed", "Fixture ack")))

    def test_enqueue_requires_existing_binding_and_does_not_create_native_thread(self):
        with self.assertRaises(ValueError):
            self.inbox.enqueue("", {"action": "set", "objective": "Fixture"})
        self.assertEqual(self.calls, [])

    def test_exact_thread_request_dispatches_once_after_restart(self):
        request = self.inbox.enqueue("native-1", {"action": "pause"})
        self.assertEqual(self.inbox.run_one(self.conn, "native-1"), (request, "confirmed", "Fixture ack"))
        self.inbox.close()
        self.inbox = GoalInbox(self.folder, "fixture-key")
        self.assertIsNone(self.inbox.run_one(self.conn, "native-1"))
        self.assertEqual(len(self.calls), 1)

    def test_binding_change_rejects_without_native_effect(self):
        for bound, conn_thread in (("replacement", "native-1"), ("native-1", "replacement")):
            self.inbox.enqueue("native-1", {"action": "pause"})
            self.conn.tid = conn_thread
            self.assertEqual(self.inbox.run_one(self.conn, bound)[1], "rejected")
        self.assertEqual(self.calls, [])

    def test_dispatch_marker_is_committed_before_any_rpc_and_unknown_never_replays(self):
        self.inbox.enqueue("native-1", {"action": "resume"})
        def inspect(command):
            other = sqlite3.connect(self.folder / "codex-goals-fixture-key.sqlite")
            self.assertEqual(other.execute("SELECT state FROM requests").fetchone()[0], "unknown")
            other.close()
            return "unknown", "Lost ack"
        self.conn.goal_control.execute = inspect
        self.assertEqual(self.inbox.run_one(self.conn, "native-1")[1], "unknown")
        self.assertIsNone(self.inbox.run_one(self.conn, "native-1"))
        self.assertEqual(self.inbox.unknown_count(), 1)

    def test_adapter_exception_stays_unknown_without_stopping_unrelated_controls(self):
        self.inbox.enqueue("native-1", {"action": "pause"})
        self.conn.goal_control.execute = mock.Mock(side_effect=RuntimeError("TOKEN=synthetic-secret"))
        result = self.inbox.run_one(self.conn, "native-1")
        self.assertEqual(result[1], "unknown")
        self.assertNotIn("synthetic-secret", result[2])
        self.conn.goal_control.execute = lambda c: ("confirmed", "Native status")
        self.inbox.enqueue("native-1", {"action": "status"})
        self.assertEqual(self.inbox.run_one(self.conn, "native-1")[1], "confirmed")
        self.assertEqual(self.inbox.unknown_count(), 1)

    def test_three_real_process_deaths_do_not_repeat_external_native_effect(self):
        for phase, effects in (("before-write", 0), ("after-write", 1), ("after-result", 1)):
            folder = self.folder / phase
            inbox = GoalInbox(folder, "fixture-key")
            inbox.enqueue("native-1", {"action": "pause"})
            inbox.close()
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("goal_fault_fixture.py")), str(folder), phase],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 71, result.stderr)
            reopened = GoalInbox(folder, "fixture-key")
            self.assertEqual(reopened.unknown_count(), 1)
            self.assertIsNone(reopened.run_one(self.conn, "native-1"))
            reopened.close()
            provider = sqlite3.connect(folder / "provider.sqlite")
            self.assertEqual(provider.execute("SELECT COUNT(*) FROM effects").fetchone()[0], effects)
            provider.close()
        self.assertEqual(self.calls, [])

    def test_unknown_schema_is_preserved_not_reset(self):
        self.inbox.db.execute("PRAGMA user_version=99")
        self.inbox.db.commit()
        with self.assertRaises(ValueError):
            GoalInbox(self.folder, "fixture-key")
        self.assertEqual(self.inbox.db.execute("PRAGMA user_version").fetchone()[0], 99)


class JoinedTests(unittest.TestCase):
    def test_goal_events_update_connection_bubble_without_clearing_busy(self):
        path = Path(__file__).parents[1] / "relay-codex-proto.py"
        spec = importlib.util.spec_from_file_location("goal_proto_fixture", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        install(module)
        with mock.patch.object(module, "read_thread", return_value="native-1"):
            conn = module.Conn("fixture-key", "/scratch/fixture")
        conn._on_notify({"method": "turn/started", "params": {"threadId": "native-1", "turn": {"id": "turn-1"}}})
        conn._on_notify({"method": "thread/goal/updated", "params": {"threadId": "native-1", "goal": native_goal(status="paused")}})
        self.assertTrue(conn.busy)
        self.assertIn("Goal: paused", conn.goal_line())
        conn.goal_notice("request-1", "Pause acknowledged")
        self.assertIn("Pause acknowledged", conn.bubble_snapshot()[3])
        conn._on_notify({"method": "thread/goal/cleared", "params": {"threadId": "foreign"}})
        self.assertIn("Goal: paused", conn.goal_line())

    def test_legacy_wildcard_chat_member_cannot_control_goals_and_owner_bypasses_queue(self):
        daemon = ccrelayd.Daemon.__new__(ccrelayd.Daemon)
        daemon.allow, daemon.allow_chats = {1001}, {"-1003"}
        daemon.me = {"username": "SyntheticKhadang"}
        daemon.bindings = SimpleNamespace(lookup=lambda c, t: ("-1003:topic:5", "/scratch/fixture"))
        daemon.say, daemon.dispatch, daemon.fetch_media = mock.Mock(), mock.Mock(), mock.Mock(return_value=[])
        message = {"message_id": 1, "chat": {"id": -1003, "is_forum": True}, "message_thread_id": 5,
                   "is_topic_message": True, "from": {"id": 999, "is_bot": False}, "text": "/goal resume"}
        daemon.on_message(message)
        daemon.dispatch.assert_not_called()
        daemon.say.assert_called_once()
        message["from"]["id"] = 1001
        daemon.on_message(message)
        self.assertTrue(daemon.dispatch.call_args.kwargs["immediate"])
        daemon.dispatch.reset_mock()
        for text, fields in (("/goal@OtherBot pause", {}), ("/goal pause", {"forward_origin": {"type": "user"}}),
                             ("/goal pause", {"via_bot": {"id": 8}})):
            daemon.on_message({**message, "text": text, **fields})
            daemon.dispatch.assert_not_called()

    def test_inject_and_main_control_paths_never_enqueue_model_text_in_any_backend(self):
        spec = importlib.util.spec_from_file_location("goal_send_fixture", Path(__file__).parents[1] / "claude-relay-send.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(module, "STATE_DIR", folder), \
                mock.patch.object(module, "save_target"), mock.patch.object(module, "is_codex", return_value=True), \
                mock.patch.object(module, "cxp", return_value=SimpleNamespace(read_thread=lambda key: "native-1")), \
                mock.patch.object(module, "deliver") as deliver:
            self.assertEqual(module.inject("cc goal pause"), "")
            deliver.assert_not_called()
            inbox = GoalInbox(folder, module.SESSION)
            self.assertEqual(inbox.db.execute("SELECT command FROM requests").fetchone()[0], '{"action": "pause"}')
            inbox.close()
            with mock.patch.object(module, "is_codex", return_value=False):
                self.assertEqual(module.inject("/goal resume"), "")
                self.assertIn("No model prompt", deliver.call_args.args[0])
        with mock.patch.object(sys, "argv", ["fixture", "/goal status"]), mock.patch.object(module, "inject", return_value="") as inject, \
                mock.patch.object(module, "JSONL", True), mock.patch.object(module, "jsonl_main") as model:
            module.main()
            inject.assert_called_once_with("/goal status")
            model.assert_not_called()

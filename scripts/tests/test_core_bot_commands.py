"""Copied-source command menus/routing; no bot credentials or native inference."""
import copy
import importlib.util
import json
import queue
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import ccrelayd
from relay_bot_commands import CommandMenus, backend_for_key, catalog, command_error, help_text, menu_plan, slash_command


class FakeBot:
    def __init__(self):
        self.menus, self.calls = {}, []
        self.lose_ack = False

    def call(self, method, params, **kwargs):
        self.calls.append((method, copy.deepcopy(params), kwargs))
        key = json.dumps(params["scope"], sort_keys=True)
        if method == "getMyCommands":
            return copy.deepcopy(self.menus.get(key, []))
        if method == "setMyCommands":
            self.menus[key] = copy.deepcopy(params["commands"])
            if self.lose_ack:
                raise OSError("Synthetic lost acknowledgment")
            return True
        raise AssertionError("Unexpected Telegram method: " + method)


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.bot = FakeBot()
        self.menus = CommandMenus(self.bot, "SyntheticKhadang", "SyntheticKhadang")

    @staticmethod
    def plan(bindings=None, owners=(1001,)):
        return menu_plan(bindings or {"-1003:topic:5": "codex"}, owners, lambda folder: folder)

    def test_whole_command_prefixes_suffixes_and_arguments(self):
        for text in ("/MODEL@SyntheticKhadang Opus", "cc model Opus", "/cc model Opus"):
            self.assertEqual(slash_command(text, "synthetickhadang")["text"], "/model Opus")
        self.assertEqual(slash_command("/goal Fix PB15\nKeep Names")["args"], "Fix PB15\nKeep Names")
        self.assertTrue(slash_command("/clear@OtherBot", "SyntheticKhadang")["foreign"])
        for text in ("Please /clear", "> /goal pause", "‘/model cx’", "goal support", "clear the issue"):
            self.assertIsNone(slash_command(text))

    def test_cancel_help_and_goal_aliases_do_not_become_prompt_text(self):
        for text in ("/stop", "/interrupt", "cc esc"):
            self.assertEqual(slash_command(text)["text"], "/cancel")
        self.assertEqual(slash_command("/commands")["text"], "/help")
        self.assertEqual(slash_command("/cc goal pause")["text"], "/goal pause")

    def test_backend_markers_pin_precedence_and_invalid_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(backend_for_key(root, "fixture"), "unknown")
            marker = root / "backend-fixture.json"
            marker.write_text('{"backend":"codex"}')
            self.assertEqual(backend_for_key(root, "fixture"), "codex")
            marker.write_text('{"backend":"claude"}')
            (root / "default-model-fixture.txt").write_text("cx\n")
            self.assertEqual(backend_for_key(root, "fixture"), "codex")
            (root / "default-model-fixture.txt").write_text("opus")
            marker.write_text("broken")
            self.assertEqual(backend_for_key(root, "fixture"), "unknown")
            for malformed in ('{"backend":null}', '{"backend":{}}', '[]', '{}'):
                marker.write_text(malformed)
                self.assertEqual(backend_for_key(root, "fixture"), "unknown")

    def test_homogeneous_chat_menu_changes_after_backend_switch(self):
        plan = self.plan({"-1003:topic:5": "claude", "-1003:topic:6": "claude"})
        commands = {item["command"] for item in plan[-1]["commands"]}
        self.assertIn("clear", commands)
        self.assertNotIn("goal", commands)
        self.assertEqual(self.menus.reconcile(plan), ["confirmed", "confirmed"])
        changed = self.plan({"-1003:topic:5": "codex", "-1003:topic:6": "codex"})
        self.menus.reconcile(changed)
        commands = {item["command"] for item in self.bot.menus[json.dumps(changed[-1]["scope"], sort_keys=True)]}
        self.assertIn("goal", commands)
        self.assertNotIn("clear", commands)

    def test_mixed_forum_union_is_order_independent_and_never_topic_scoped(self):
        one = self.plan({"-1003:topic:5": "claude", "-1003:topic:6": "codex"})
        two = self.plan({"-1003:topic:6": "codex", "-1003:topic:5": "claude"})
        self.assertEqual(one, two)
        descriptions = {item["command"]: item["description"] for item in one[-1]["commands"]}
        self.assertIn("[Claude]", descriptions["clear"])
        self.assertIn("[Codex]", descriptions["goal"])
        for entry in one:
            self.assertNotIn("message_thread_id", entry["scope"])
            self.assertNotIn(entry["scope"]["type"], {"default", "all_group_chats", "chat_administrators"})

    def test_public_and_private_menus_do_not_inherit_owner_controls(self):
        plan = self.plan({"-1003": "codex", "1001": "claude", "999": "codex"})
        for entry in plan:
            scope = entry["scope"]
            if scope == {"type": "chat", "chat_id": -1003} or scope["chat_id"] == 999:
                self.assertEqual([item["command"] for item in entry["commands"]], ["help"])
            if scope["chat_id"] == 1001:
                self.assertEqual(scope["type"], "chat")
                self.assertIn("clear", {item["command"] for item in entry["commands"]})
        self.assertEqual(len(self.plan(owners=())), 1)

    def test_wrong_bot_identity_and_invalid_bindings_fail_before_any_write(self):
        with self.assertRaises(ValueError):
            CommandMenus(self.bot, "OtherBot", "SyntheticKhadang")
        with self.assertRaises(ValueError):
            self.plan({"arbitrary:topic:5": "claude"})
        with self.assertRaises(ValueError):
            self.plan(owners=(True,))
        self.assertEqual(self.bot.calls, [])

    def test_existing_unrelated_commands_preserved_and_unchanged_menu_is_not_written(self):
        plan = self.plan()
        key = json.dumps(plan[-1]["scope"], sort_keys=True)
        unrelated = {"command": "custom", "description": "Keep this existing command"}
        self.bot.menus[key] = [unrelated, {"command": "clear", "description": "Old Claude control"}]
        self.menus.reconcile(plan)
        self.assertIn(unrelated, self.bot.menus[key])
        before = sum(method == "setMyCommands" for method, _, _ in self.bot.calls)
        self.assertEqual(self.menus.reconcile(plan), ["unchanged", "unchanged"])
        self.assertEqual(sum(method == "setMyCommands" for method, _, _ in self.bot.calls), before)
        for _, _, kwargs in self.bot.calls:
            self.assertEqual(kwargs["max_wait"], 0)

    def test_lost_menu_write_ack_is_read_before_another_mutation(self):
        self.bot.lose_ack = True
        self.assertEqual(self.menus.reconcile(self.plan()), ["unconfirmed", "unconfirmed"])
        self.bot.lose_ack = False
        before = len(self.bot.calls)
        self.assertEqual(self.menus.reconcile(self.plan()), ["unchanged", "unchanged"])
        self.assertTrue(all(method == "getMyCommands" for method, _, _ in self.bot.calls[before:]))

    def test_bad_readback_never_overwrites_menu_or_logs_exception_secrets(self):
        report = mock.Mock()
        menus = CommandMenus(self.bot, "SyntheticKhadang", "SyntheticKhadang", report)
        with mock.patch.object(self.bot, "call", return_value=None) as call:
            self.assertEqual(menus.reconcile(self.plan()), ["unconfirmed", "unconfirmed"])
            self.assertTrue(all(args.args[0] == "getMyCommands" for args in call.call_args_list))
        with mock.patch.object(self.bot, "call", side_effect=OSError("SYNTHETIC_SECRET")):
            menus.reconcile(self.plan())
        self.assertNotIn("SYNTHETIC_SECRET", str(report.call_args_list))

    def test_plan_cannot_broaden_scope_or_overwrite_an_unrelated_language_menu(self):
        for scope, language in (({"type": "default"}, ""), ({"type": "chat_administrators", "chat_id": -1003}, ""),
                                ({"type": "chat", "chat_id": -1003, "message_thread_id": 5}, ""),
                                ({"type": "chat", "chat_id": -1003}, "fa")):
            plan = self.plan()
            plan.append({"scope": scope, "language_code": language, "commands": catalog(set(), False)})
            with self.assertRaises(ValueError):
                self.menus.reconcile(plan)
            self.assertEqual(self.bot.calls, [])

    def test_full_unrelated_menu_is_preserved_when_merge_exceeds_provider_limit(self):
        plan = self.plan()
        key = json.dumps(plan[-1]["scope"], sort_keys=True)
        original = [{"command": f"custom_{number}", "description": "Preserve existing command"} for number in range(100)]
        self.bot.menus[key] = copy.deepcopy(original)
        self.assertEqual(self.menus.reconcile(plan)[-1], "unconfirmed")
        self.assertEqual(self.bot.menus[key], original)

    def test_retired_binding_scope_is_replaced_with_help_not_global_fallback(self):
        self.menus.reconcile(self.plan())
        self.menus.reconcile([])
        for menu in self.bot.menus.values():
            self.assertEqual([item["command"] for item in menu], ["help"])
        self.assertFalse(any(method == "deleteMyCommands" for method, _, _ in self.bot.calls))

    def test_contextual_help_and_capabilities_match_current_topic_not_last_menu(self):
        self.assertIn("/clear", help_text("claude"))
        self.assertNotIn("/goal —", help_text("claude"))
        self.assertIn("/goal —", help_text("codex"))
        self.assertNotIn("/clear —", help_text("codex"))
        self.assertIn("No model prompt", command_error("/clear", "codex"))
        self.assertIn("No model prompt", command_error("/goal", "claude"))
        self.assertEqual(command_error("/model cx", "codex"), "")
        self.assertIn("unverified", command_error("/clear", "unknown"))
        self.assertNotIn("cancel", {item["command"] for item in catalog({"unknown"})})
        self.assertEqual([item["command"] for item in catalog({"codex"}, False)], ["help"])


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.daemon = ccrelayd.Daemon.__new__(ccrelayd.Daemon)
        self.daemon.allow, self.daemon.allow_chats = {1001}, {"-1003"}
        self.daemon.me = {"username": "SyntheticKhadang"}
        self.daemon.bindings = SimpleNamespace(lookup=lambda *_: ("-1003:topic:5", "/scratch/fixture"))
        self.daemon.backend_for_folder = mock.Mock(return_value="codex")
        self.daemon.say, self.daemon.dispatch = mock.Mock(), mock.Mock()
        self.daemon.fetch_media = mock.Mock(return_value=[])
        self.message = {"message_id": 1, "chat": {"id": -1003, "is_forum": True}, "message_thread_id": 5,
                        "is_topic_message": True, "from": {"id": 1001, "is_bot": False}}

    def test_own_bot_suffix_is_removed_and_command_bypasses_topic_work_queue(self):
        self.daemon.on_message({**self.message, "text": "/goal@SyntheticKhadang Fix PB15"})
        args = self.daemon.dispatch.call_args
        self.assertEqual(args.args[6], "/goal Fix PB15")
        self.assertTrue(args.kwargs["immediate"])
        self.daemon.dispatch.reset_mock()
        self.daemon.backend_for_folder.return_value = "claude"
        self.daemon.on_message({**self.message, "text": "/clear@SyntheticKhadang"})
        self.assertEqual(self.daemon.dispatch.call_args.args[6], "/clear")

    def test_model_buttons_require_owner_and_bypass_prompt_queue(self):
        self.daemon.bot = SimpleNamespace(call=mock.Mock())
        callback = {"id": "fixture", "from": {"id": 999}, "message": self.message,
                    "data": "ccmodel:abcdef123456:0"}
        self.daemon.on_callback(callback)
        self.daemon.dispatch.assert_not_called()
        self.daemon.on_callback({**callback, "from": {"id": 1001}})
        self.assertTrue(self.daemon.dispatch.call_args.kwargs["immediate"])

    def test_foreign_bot_all_command_types_are_ignored_before_admin_or_prompt(self):
        self.daemon.cmd_unbind = mock.Mock()
        for text in ("/unbind@OtherBot", "/newcc@OtherBot 123456", "/clear@OtherBot", "/unknown@OtherBot",
                     "/new-cc@OtherBot 123456", "/cc-status@OtherBot", "/unbind-claude-code@OtherBot"):
            self.daemon.on_message({**self.message, "text": text})
        self.daemon.cmd_unbind.assert_not_called()
        self.daemon.dispatch.assert_not_called()
        self.daemon.say.assert_not_called()

    def test_wildcard_member_and_forwarded_owner_cannot_use_controls(self):
        for text in ("/clear", "/compact", "/goal pause", "/model cx", "cc goal pause", "/cc model cx",
                     "callback_data: ccmodel:abcdef123456:0"):
            self.daemon.on_message({**self.message, "from": {"id": 999}, "text": text})
            for field in ("forward_origin", "forward_from_chat", "via_bot"):
                self.daemon.on_message({**self.message, "text": text, field: {"id": 1001}})
        self.daemon.dispatch.assert_not_called()
        self.daemon.fetch_media.assert_not_called()

    def test_help_is_local_deterministic_and_does_not_launch_a_backend(self):
        self.daemon.on_message({**self.message, "text": "/help"})
        self.assertIn("Codex topic commands", self.daemon.say.call_args.args[2])
        self.daemon.dispatch.assert_not_called()
        self.daemon.on_message({**self.message, "from": {"id": 999}, "text": "/help"})
        self.assertIn("authorized owner", self.daemon.say.call_args.args[2])
        self.daemon.bindings = SimpleNamespace(lookup=lambda *_: (None, None))
        self.daemon.on_message({**self.message, "text": "/help"})
        self.assertIn("not bound", self.daemon.say.call_args.args[2])

    def test_wrong_tool_command_is_rejected_without_dispatch(self):
        for text in ("/clear", "/compact", "/unq", "/anything"):
            self.daemon.on_message({**self.message, "text": text})
        self.daemon.backend_for_folder.return_value = "claude"
        self.daemon.on_message({**self.message, "text": "/goal pause"})
        self.daemon.dispatch.assert_not_called()

    def test_execution_rechecks_backend_even_when_discovery_or_intake_was_stale(self):
        spec = importlib.util.spec_from_file_location("command_send_fixture", Path(__file__).parents[1] / "claude-relay-send.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.object(module, "save_target"), mock.patch.object(module, "backend_name", return_value="codex"), \
                mock.patch.object(module, "deliver") as deliver, mock.patch.object(module, "cxp") as native, \
                mock.patch.object(module, "type_prompt") as prompt:
            module.inject("/clear")
            self.assertIn("No model prompt", deliver.call_args.args[0])
            native.assert_not_called()
            prompt.assert_not_called()
        with mock.patch.object(module, "sys", SimpleNamespace(argv=["fixture", "/model cx"])), \
                mock.patch.object(module, "inject", return_value="") as inject, mock.patch.object(module, "JSONL", True), \
                mock.patch.object(module, "jsonl_main") as model:
            module.main()
            inject.assert_called_once_with("/model cx")
            model.assert_not_called()

    def test_menu_network_work_is_queued_and_coalesced_outside_intake(self):
        daemon = self.daemon
        daemon.command_menus = mock.Mock()
        daemon.menu_last_check = 0
        daemon.menu_jobs = queue.Queue(maxsize=1)
        daemon.bindings.load = lambda: {"-1003:topic:5": "/scratch/fixture"}
        daemon.sync_command_menus(force=True)
        daemon.backend_for_folder.return_value = "claude"
        daemon.sync_command_menus(force=True)
        daemon.command_menus.reconcile.assert_not_called()
        self.assertEqual(daemon.menu_jobs.qsize(), 1)
        current = daemon.menu_jobs.get_nowait()
        self.assertIn("clear", {item["command"] for item in current[-1]["commands"]})
        self.assertNotIn("goal", {item["command"] for item in current[-1]["commands"]})

    def test_cli_menu_plan_never_loads_token_polls_or_launches_a_daemon(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bindings = root / "bindings.json"
            bindings.write_text(json.dumps({"-1003:topic:5": str(root)}))
            config = root / "config.json"
            config.write_text(json.dumps({"bindings": str(bindings), "allow_users": [1001]}))
            with mock.patch.object(ccrelayd.sys, "argv", ["fixture", "--config", str(config), "--command-menu-plan"]), \
                    mock.patch.object(ccrelayd, "RELAY_WORK", str(root)), mock.patch.object(ccrelayd, "Daemon") as daemon, \
                    mock.patch.object(ccrelayd.relay_tg, "Bot") as bot, \
                    mock.patch.object(ccrelayd.relay_tg, "load_token") as token, mock.patch("builtins.print") as output:
                ccrelayd.main()
                result = json.loads(output.call_args.args[0])
                self.assertIs(result["network"], False)
                self.assertIs(result["state_mutation"], False)
                self.assertEqual(result["plan"][-1]["scope"]["type"], "chat_member")
                daemon.assert_not_called()
                bot.assert_not_called()
                token.assert_not_called()

    def test_one_shot_menu_registration_only_reads_identity_and_reconciles_scopes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bindings = root / "bindings.json"
            bindings.write_text(json.dumps({"-1003:topic:5": str(root)}))
            config = root / "config.json"
            config.write_text(json.dumps({"bindings": str(bindings), "allow_users": [1001], "env": "synthetic"}))
            bot = mock.Mock()
            bot.call.return_value = {"username": "SyntheticKhadang"}
            with mock.patch.object(ccrelayd.sys, "argv", ["fixture", "--config", str(config), "--sync-command-menu", "--expect-bot", "SyntheticKhadang"]), \
                    mock.patch.object(ccrelayd, "RELAY_WORK", str(root)), mock.patch.object(ccrelayd, "Daemon") as daemon, \
                    mock.patch.object(ccrelayd.relay_tg, "Bot", return_value=bot), \
                    mock.patch.object(ccrelayd.relay_tg, "load_token", return_value="SYNTHETIC"), \
                    mock.patch.object(ccrelayd, "CommandMenus") as menus, mock.patch("builtins.print"):
                menus.return_value.reconcile.return_value = ["confirmed", "confirmed"]
                ccrelayd.main()
                bot.call.assert_called_once_with("getMe", timeout=3, max_wait=0)
                menus.return_value.reconcile.assert_called_once()
                daemon.assert_not_called()
                bot.call.side_effect = OSError("SYNTHETIC_SECRET_URL")
                with mock.patch("builtins.print") as output, self.assertRaises(SystemExit) as stopped:
                    ccrelayd.main()
                self.assertEqual(stopped.exception.code, 1)
                self.assertNotIn("SYNTHETIC_SECRET_URL", str(output.call_args_list))

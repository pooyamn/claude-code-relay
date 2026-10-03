import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from relay_model_controls import control, handle, models, retired, resolve_picker, save_picker


class Native:
    def __init__(self):
        self.calls = []
        self.thread = {"id": "thread-a", "model": "test-a", "reasoningEffort": "high"}
        self.catalog = [{"id": name, "model": name, "displayName": name, "hidden": False,
                         "defaultReasoningEffort": "low", "supportedReasoningEfforts": [
                             {"reasoningEffort": e, "description": e} for e in efforts]}
                        for name, efforts in [("test-a", ["low", "high"]), ("test-b", ["low", "medium"])]]
        self.lose_ack = False

    def __call__(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "model/list":
            return {"data": self.catalog, "nextCursor": None}
        if method == "thread/read":
            return {"thread": copy.deepcopy(self.thread)}
        if method == "thread/settings/update":
            self.thread.update(model=params["model"], reasoningEffort=params["effort"])
            if self.lose_ack:
                raise TimeoutError()
            return {}
        raise AssertionError(method)


class ModelTests(unittest.TestCase):
    def test_picker_reads_native_catalog_without_inference_or_resume(self):
        native = Native()
        text, options = control(native, "thread-a", "model", "")
        self.assertIn("test-a", text)
        self.assertEqual(options, [("test-a", "/model test-a"), ("test-b", "/model test-b")])
        self.assertEqual([c[0] for c in native.calls], ["thread/read", "model/list"])

    def test_model_update_keeps_thread_and_chooses_supported_effort(self):
        native = Native()
        text, _ = control(native, "thread-a", "model", "test-b")
        self.assertIn("subsequent turns", text)
        self.assertEqual(native.calls[-2], ("thread/settings/update", {
            "threadId": "thread-a", "model": "test-b", "effort": "low"}))
        self.assertEqual(native.calls[-1][0], "thread/read")

    def test_explicit_effort_and_idempotent_selection(self):
        native = Native()
        control(native, "thread-a", "effort", "low")
        before = len(native.calls)
        control(native, "thread-a", "model", "test-a low")
        self.assertNotIn("thread/settings/update", [c[0] for c in native.calls[before:]])

    def test_invalid_effort_and_retired_model_never_mutate(self):
        for args in [("effort", "ultra"), ("model", "ox"), ("model", "test-b high")]:
            native = Native()
            control(native, "thread-a", *args)
            self.assertNotIn("thread/settings/update", [c[0] for c in native.calls])
        for name in ("Kimi", "ik3", "k3", "ox", "oxa", "cox", "stealth/ox-alpha", "opencode/x-preview-f-free"):
            self.assertTrue(retired(name))

    def test_lost_ack_does_not_replay_or_claim_success(self):
        native = Native()
        native.lose_ack = True
        text, _ = control(native, "thread-a", "model", "test-b")
        self.assertIn("unconfirmed", text)
        self.assertEqual(sum(c[0] == "thread/settings/update" for c in native.calls), 1)

    def test_foreign_thread_and_absent_thread_never_mutate(self):
        native = Native()
        with self.assertRaises(ValueError):
            control(native, "thread-other", "model", "test-b")
        self.assertIn("no Codex thread", control(native, "", "model", "")[0])
        self.assertNotIn("thread/settings/update", [c[0] for c in native.calls])

    def test_picker_bound_to_thread_destination_and_latest_menu(self):
        with tempfile.TemporaryDirectory() as state:
            choices = [("Synthetic", "/model test-a")]
            callback = "callback_data: " + save_picker(state, "s", "t", ["-1", "5"], choices)[0]
            self.assertEqual(resolve_picker(callback, state, "s", "t", ["-1", "5"]), "/model test-a")
            for tid, dest in [("other", ["-1", "5"]), ("t", ["-1", "6"])]:
                with self.assertRaises(ValueError):
                    resolve_picker(callback, state, "s", tid, dest)
            save_picker(state, "s", "t", ["-1", "5"], choices)
            with self.assertRaises(ValueError):
                resolve_picker(callback, state, "s", "t", ["-1", "5"])

    def test_catalog_pagination(self):
        calls = []
        def rpc(method, params):
            calls.append(params)
            return {"data": [], "nextCursor": "page2" if params["cursor"] is None else None}
        self.assertEqual(models(rpc), [])
        self.assertEqual(len(calls), 2)


class ModelRoutingTests(unittest.TestCase):
    def setUp(self):
        self.sender = SimpleNamespace(
            CHAT_ID="-1003", THREAD_ID="53", SESSION="fixture", STATE_DIR="/scratch/fixture",
            is_codex=mock.Mock(return_value=True), backend_name=mock.Mock(return_value="codex"),
            cxp=mock.Mock(return_value=SimpleNamespace(read_thread=lambda _: "thread-a")),
            BUSY=SimpleNamespace(search=mock.Mock(return_value=False)), pane=mock.Mock(return_value=""),
            restart_with_model=mock.Mock(), deliver=mock.Mock(), tg_buttons=mock.Mock())
        self.native = Native()
        self.rpc = mock.patch("relay_model_controls.NativeRPC")
        self.rpc_mock = self.rpc.start()
        self.rpc_mock.return_value.__enter__.return_value = self.native
        self.addCleanup(self.rpc.stop)

    def test_legacy_claude_model_aliases_switch_from_codex_before_catalog(self):
        # OpenClaw strips the cc prefix; both transports must retain the alias.
        for prompt, model in [("cc model opus", "opus"), ("/model Opus", "Opus"),
                              ("/cc model sonnet", "sonnet"), ("/model haiku", "haiku"),
                              ("/model claude-opus-fixture[1m]", "claude-opus-fixture[1m]")]:
            with self.subTest(prompt=prompt), mock.patch("relay_model_controls._active", return_value=False):
                self.assertTrue(handle(self.sender, prompt))
                self.sender.restart_with_model.assert_called_once_with(model)
                self.sender.restart_with_model.reset_mock()
        self.assertEqual(self.native.calls, [])
        self.sender.deliver.assert_not_called()

    def test_legacy_cx_alias_switches_claude_and_is_noop_in_codex(self):
        self.sender.is_codex.return_value = False
        self.sender.backend_name.return_value = "claude"
        self.assertTrue(handle(self.sender, "cc model cx"))
        self.sender.restart_with_model.assert_called_once_with("cx")
        self.sender.restart_with_model.reset_mock()
        self.sender.is_codex.return_value = True
        self.sender.backend_name.return_value = "codex"
        self.assertTrue(handle(self.sender, "/model cx"))
        self.sender.restart_with_model.assert_not_called()
        self.assertIn("already", self.sender.deliver.call_args.args[0])
        self.assertEqual(self.native.calls, [])

    def test_tool_switch_alias_cannot_interrupt_active_or_unverified_turn(self):
        for result in [True, OSError("SYNTHETIC_INTERNAL_DETAIL")]:
            options = {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}
            for command in ["cc model opus", "/backend claude"]:
                with self.subTest(command=command, result=type(result).__name__), \
                        mock.patch("relay_model_controls._active", **options):
                    self.assertTrue(handle(self.sender, command))
                    self.sender.restart_with_model.assert_not_called()
                    self.assertNotIn("SYNTHETIC_INTERNAL_DETAIL", self.sender.deliver.call_args.args[0])
        self.assertEqual(self.native.calls, [])

    def test_codex_models_still_update_native_thread_and_unknowns_never_switch(self):
        self.assertTrue(handle(self.sender, "cc model test-b"))
        self.assertIn("thread/settings/update", [method for method, _ in self.native.calls])
        self.sender.restart_with_model.assert_not_called()
        before = len(self.native.calls)
        self.assertTrue(handle(self.sender, "cc model unknown-model"))
        self.assertNotIn("thread/settings/update", [method for method, _ in self.native.calls[before:]])
        self.sender.restart_with_model.assert_not_called()

    def test_claude_model_alias_stays_a_model_change_in_claude(self):
        self.sender.is_codex.return_value = False
        self.sender.backend_name.return_value = "claude"
        self.assertTrue(handle(self.sender, "cc model opus"))
        self.sender.restart_with_model.assert_called_once_with("opus")
        self.assertEqual(self.native.calls, [])

    def test_sender_consumes_opus_control_without_queuing_or_typing_a_prompt(self):
        spec = importlib.util.spec_from_file_location(
            "model_send_fixture", Path(__file__).parents[1] / "claude-relay-send.py")
        sender = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sender)
        with mock.patch.object(sender, "save_target"), \
                mock.patch.object(sender, "is_codex", return_value=True), \
                mock.patch.object(sender, "backend_name", return_value="codex"), \
                mock.patch.object(sender, "cxp") as native, \
                mock.patch.object(sender, "restart_with_model") as switch, \
                mock.patch.object(sender, "type_prompt") as prompt, \
                mock.patch("relay_model_controls._active", return_value=False):
            native.return_value.read_thread.return_value = "thread-a"
            self.assertEqual(sender.inject("/model opus"), "")
            switch.assert_called_once_with("opus")
            native.return_value.enqueue.assert_not_called()
            prompt.assert_not_called()
        self.assertEqual(self.native.calls, [])


if __name__ == "__main__":
    unittest.main()

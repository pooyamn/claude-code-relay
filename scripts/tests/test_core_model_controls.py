import copy
import tempfile
import unittest

from relay_model_controls import control, models, retired, resolve_picker, save_picker


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


if __name__ == "__main__":
    unittest.main()

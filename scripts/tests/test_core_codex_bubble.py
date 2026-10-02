"""Cumulative Codex UI regressions. No model, socket, Telegram or host config."""
import importlib.util
import json
import queue
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from relay_codex_bubble import (BubblePages, BubbleState, DeliveryUncertain, PendingDelivery,
                                TurnView, install, redact)
from relay_tg import _split_for_html, md_to_html


def event(method, item=None, thread="native-1", turn="turn-1", **params):
    p = {"threadId": thread, **({"turn": turn} if isinstance(turn, dict) else {"turnId": turn}), **params}
    if item is not None:
        p["item"] = item
    return {"method": method, "params": p}


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.view = TurnView("native-1")
        self.view.observe(event("turn/started", turn={"id": "turn-1"}))

    def message(self, mid, text, **fields):
        self.view.observe(event("item/completed", {"id": mid, "type": "agentMessage", "text": text, **fields}))

    def test_screenshot_messages_and_async_question_survive_newer_commentary(self):
        self.message("m1", "I’m tracing each routed path from its MCU pin number.", phase="commentary")
        self.message("question-1", "Should U122 pins 10 and 14 connect to PB15 (MCU pin 76)?",
                     phase="final_answer", delivery="async", questions=[{"title": "PB15?"}])
        self.message("m2", "51 of the 52 paths now have an unambiguous mapping.", phase="commentary")
        body = self.view.render()
        for text in ("tracing each routed", "❓ Question", "Should U122", "51 of the 52"):
            self.assertIn(text, body)
        self.assertEqual(self.view.status, "inProgress")

    def test_tools_show_starts_actions_and_completion_without_duplicate_entries(self):
        tool = {"id": "tool-1", "type": "commandExecution", "status": "inProgress",
                "commandActions": [{"type": "read", "name": "gen_bank.py"},
                                   {"type": "search", "query": "PB15"}]}
        self.view.observe(event("item/started", tool))
        self.assertIn("⏳ Read gen_bank.py; Search PB15", self.view.render())
        self.view.observe(event("item/completed", {**tool, "status": "completed", "exitCode": 0}))
        self.view.observe(event("item/completed", {**tool, "status": "completed", "exitCode": 0}))
        self.assertEqual(self.view.render(), "✓ Read gen_bank.py; Search PB15")
        self.assertEqual(len(self.view.items), 1)

    def test_wire_case_variants_and_failed_exit_code(self):
        for index, typ in enumerate(("commandExecution", "command_execution", "CommandExecution")):
            self.view.observe(event("item/completed", {"id": str(index), "type": typ, "command": "make test",
                                                       "status": "failed", "exitCode": 2}))
        self.assertEqual(self.view.render().count("✗ Run make test [exit 2]"), 3)

    def test_no_private_reasoning_shell_output_or_raw_mcp_arguments_are_published(self):
        self.view.observe(event("item/completed", {"id": "reason", "type": "reasoning", "text": "PRIVATE REASON"}))
        self.view.observe(event("item/completed", {"id": "exec", "type": "commandExecution", "command": "make test",
                                                   "aggregatedOutput": "PRIVATE OUTPUT"}))
        self.view.observe(event("item/completed", {"id": "mcp", "type": "mcpToolCall", "server": "kicad",
                                                   "tool": "inspect", "arguments": {"token": "PRIVATE ARG"}}))
        body = self.view.render()
        self.assertIn("Tool kicad.inspect", body)
        self.assertNotIn("PRIVATE", body)

    def test_cross_thread_and_stale_turn_notifications_cannot_change_view(self):
        self.message("ours", "Our message")
        for bad in (event("turn/started", thread="review-thread", turn={"id": "review-turn"}),
                    event("item/completed", {"id": "foreign", "type": "agentMessage", "text": "All four review gaps"},
                          thread="review-thread"), event("turn/completed", turn="old-turn"),
                    {"method": "item/completed", "params": {"item": {"id": "unscoped", "type": "agentMessage", "text": "bad"}}}):
            self.assertFalse(self.view.observe(bad))
        self.assertEqual(self.view.render(), "Our message")
        self.assertEqual(self.view.status, "inProgress")

    def test_delta_and_completed_text_share_one_item_and_late_start_does_not_erase_it(self):
        self.view.observe(event("item/agentMessage/delta", itemId="m1", delta="Hello"))
        self.view.observe(event("item/agentMessage/delta", itemId="m1", delta=" world"))
        self.message("m1", "Hello world!")
        self.view.observe(event("item/started", {"id": "m1", "type": "agentMessage", "text": ""}))
        self.view.observe(event("item/agentMessage/delta", itemId="m1", delta="late duplicate"))
        self.assertEqual(self.view.render(), "Hello world!")

    def test_resume_snapshot_restores_all_items_without_overwriting_newer_live_text(self):
        self.message("m2", "Newer complete text")
        self.view.hydrate({"id": "turn-1", "status": "inProgress", "items": [
            {"id": "m1", "type": "agentMessage", "text": "Earlier text"},
            {"id": "m2", "type": "agentMessage", "text": "Stale partial"},
            {"id": "exec", "type": "commandExecution", "command": "make", "status": "inProgress"}]})
        self.assertEqual(self.view.render(), "Earlier text\n\nNewer complete text\n\n⏳ Run make")
        self.view.hydrate({"id": "older-turn", "items": [{"id": "bad", "type": "agentMessage", "text": "wrong"}]})
        self.assertNotIn("wrong", self.view.render())

    def test_new_turn_resets_history_but_steering_user_item_does_not(self):
        self.message("m1", "Keep me while steering")
        self.view.observe(event("item/completed", {"id": "user", "type": "userMessage", "text": "What?"}))
        self.assertIn("Keep me", self.view.render())
        self.assertIn("💬 User\nWhat?", self.view.render())
        self.view.observe(event("turn/started", turn={"id": "turn-2"}))
        self.assertEqual(self.view.render(), "")

    def test_native_app_user_message_content_is_retained_and_redacted(self):
        self.view.hydrate({"id": "turn-1", "status": "inProgress", "items": [
            {"id": "prompt", "type": "userMessage", "content": [
                {"type": "text", "text": "Have you updated the source? Pushed?"}]},
            {"id": "reply", "type": "agentMessage", "text": "TOKEN=synthetic-secret-value Updated locally."}]})
        body = self.view.render()
        self.assertIn("💬 User\nHave you updated the source? Pushed?", body)
        self.assertIn("Updated locally.", body)
        self.assertNotIn("synthetic-secret-value", body)

    def test_request_question_is_visible_without_answering_or_ending_turn(self):
        request = event("item/tool/requestUserInput", itemId="question", questions=[
            {"question": "PB15?", "options": [{"label": "Yes"}, {"label": "No"}]}])
        self.view.observe(request)
        self.assertIn("❓ Question\nPB15?\n- Yes\n- No", self.view.render())
        self.assertEqual(self.view.status, "inProgress")

    def test_failed_turn_retains_history_and_exposes_real_error(self):
        self.message("m1", "Earlier work")
        self.view.observe(event("turn/completed", turn={"id": "turn-1", "status": "failed",
                                                       "error": {"message": "Model at capacity"}}))
        self.assertEqual(self.view.status, "failed")
        self.assertIn("Earlier work", self.view.render())
        self.assertIn("Model at capacity", self.view.render())

    def test_tool_credentials_are_redacted(self):
        source = "TOKEN=synthetic-secret-value curl -H 'Bearer synthetic-credential' https://api.telegram.org/bot123:synthetic_secret/getMe"
        body = redact(source)
        self.assertNotIn("synthetic-secret-value", body)
        self.assertNotIn("synthetic-credential", body)
        self.assertNotIn("synthetic_secret", body)


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("fixture_codex_proto", Path(__file__).parents[1] / "relay-codex-proto.py")
        self.proto = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.proto)
        self.base = self.proto.Conn
        install(self.proto)
        with mock.patch.object(self.proto, "read_thread", return_value="native-1"):
            self.conn = self.proto.Conn("fixture-key", "/scratch/fixture")
        self.conn.tid = "native-1"

    def test_foreign_completion_cannot_clear_native_busy_or_supply_final_reply(self):
        self.conn._on_notify(event("turn/started", turn={"id": "turn-1"}))
        self.conn._on_notify(event("item/completed", {"id": "own", "type": "agentMessage", "text": "Ours"}))
        self.conn._on_notify(event("turn/started", thread="foreign", turn={"id": "foreign-turn"}))
        self.conn._on_notify(event("item/completed", {"id": "bad", "type": "agentMessage", "text": "All four review gaps"},
                                   thread="foreign", turn="foreign-turn"))
        self.conn._on_notify(event("turn/completed", thread="foreign", turn={"id": "foreign-turn"}))
        self.assertTrue(self.conn.busy)
        self.assertEqual(self.conn.take_final(), "")
        self.assertEqual(self.conn.live_text(), "Ours")

    def test_resume_reply_hydrates_active_turn_and_protects_exact_binding(self):
        response = {"result": {"thread": {"id": "native-1", "turns": [{"id": "turn-1", "status": "inProgress",
            "items": [{"id": "exec", "type": "commandExecution", "command": "make", "status": "inProgress"}]}]}}}
        with mock.patch.object(self.base, "_send", return_value=42), mock.patch.object(self.base, "_wait", return_value=response):
            self.conn._wait(self.conn._send("thread/resume", {"threadId": "native-1"}))
        self.assertEqual(self.conn.turn_id, "turn-1")
        self.assertTrue(self.conn.busy)
        self.assertIn("⏳ Run make", self.conn.live_text())
        response["result"]["thread"]["id"] = "foreign"
        with mock.patch.object(self.base, "_send", return_value=43), mock.patch.object(self.base, "_wait", return_value=response):
            self.conn._wait(self.conn._send("thread/resume", {"threadId": "native-1"}))
        self.assertEqual(self.conn.view.thread_id, "native-1")


class PagesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = BubbleState(self.tmp.name, "native-1", "turn-1", "-100", "53")
        self.sends, self.edits, self.now = [], [], 0
        def send(text):
            self.sends.append(text)
            return str(len(self.sends))
        self.send = send
        self.edit = lambda mid, text: self.edits.append((mid, text)) or True
        self.pages = BubblePages(self.state, send, self.edit,
                                 _split_for_html, lambda: self.now)

    def test_updates_and_final_answer_edit_same_message_instead_of_posting_final(self):
        self.pages.update("First message")
        self.now = 5
        self.pages.update("First message\n\nSecond message")
        self.pages.update("First message\n\nSecond message\n\nFinal answer", "completed", force=True)
        self.assertEqual(len(self.sends), 1)
        self.assertEqual([mid for mid, text in self.edits], ["1", "1"])
        self.assertIn("Final answer", self.edits[-1][1])
        self.assertTrue(self.edits[-1][1].startswith("✓ Done"))

    def test_rolling_tail_is_one_message_with_elapsed_footer_and_full_history_intact(self):
        pages = BubblePages(self.state, self.send, self.edit, _split_for_html,
                            clock=lambda: self.now, rolling=True, started_at=1000,
                            wall_clock=lambda: 4665)
        body = "Earlier activity\n" + "x" * 16000 + "\nNewest live update"
        self.assertTrue(pages.update(body))
        self.assertEqual(len(self.sends), 1)
        self.assertIn("Newest live update", self.sends[0])
        self.assertNotIn("Earlier activity", self.sends[0])
        self.assertTrue(self.sends[0].endswith("Working (1h 1m 5s)"))
        self.assertLessEqual(len(md_to_html(self.sends[0]).encode("utf-16-le")) // 2, 4096)
        self.now = 5
        pages.update(body + "\nFinal reply", "completed", force=True)
        self.assertEqual(len(self.sends), 1)
        self.assertIn("Final reply", self.edits[-1][1])
        self.assertTrue(self.edits[-1][1].endswith("Done (1h 1m 5s)"))

    def test_rolling_emoji_escaping_and_long_fences_still_fit_one_message(self):
        pages = BubblePages(self.state, self.send, self.edit, _split_for_html, rolling=True)
        for body in ("😀" * 12000 + "NEW", "&" * 12000 + "NEW", "```py\n" + "x" * 12000 + "NEW\n```"):
            text = pages.rolling_text(body, "inProgress")
            self.assertIn("NEW", text)
            self.assertLessEqual(len(md_to_html(text).encode("utf-16-le")) // 2, 4096)
            self.assertTrue(text.splitlines()[-1].startswith("Working ("))
            self.assertEqual(text.count("```") % 2, 0)

    def test_late_send_ack_is_polled_without_a_duplicate_send(self):
        receipt = [None, "42"]
        send = mock.Mock(side_effect=PendingDelivery(lambda: receipt.pop(0)))
        pages = BubblePages(self.state, send, self.edit, _split_for_html, clock=lambda: self.now)
        self.assertFalse(pages.update("First"))
        self.assertFalse(pages.update("Newer"))
        self.now = 5
        self.assertTrue(pages.update("Newer"))
        send.assert_called_once()
        self.assertEqual(self.state.ids, ["42"])
        self.assertEqual(self.edits[-1], ("42", "⏳ Working\n\nNewer"))

    def test_late_edit_ack_fences_newer_content_until_same_request_is_confirmed(self):
        self.pages.update("First")
        receipt = [None, True]
        edit = mock.Mock(side_effect=[PendingDelivery(lambda: receipt.pop(0)), True])
        pages = BubblePages(self.state, self.send, edit, _split_for_html, clock=lambda: self.now)
        self.assertFalse(pages.update("Second"))
        self.assertFalse(pages.update("Third"))
        self.assertIn("Second", self.state.pending_edit["text"])
        self.now = 5
        self.assertTrue(pages.update("Third"))
        self.assertIsNone(self.state.pending_edit)
        self.assertEqual(edit.call_count, 2)
        self.assertEqual(edit.call_args_list[0].args, ("1", "⏳ Working\n\nSecond"))
        self.assertEqual(edit.call_args_list[1].args, ("1", "⏳ Working\n\nThird"))

    def test_explicit_restart_reconciliation_replays_only_saved_same_id_edit_before_newer_text(self):
        self.pages.update("First")
        self.state.pending_edit = {"position": 0, "text": "Unconfirmed second"}
        self.state.save()
        edits = []
        pages = BubblePages(BubbleState(self.tmp.name, "native-1", "turn-1", "-100", "53"),
                            self.send, lambda mid, text: edits.append((mid, text)) or True,
                            _split_for_html, reconcile_edits=True)
        self.assertTrue(pages.update("Third"))
        self.assertEqual(edits, [("1", "Unconfirmed second"), ("1", "⏳ Working\n\nThird")])
        self.assertEqual(len(self.sends), 1)

    def test_size_limit_uses_continuations_without_discarding_content(self):
        body = "start\n" + "x" * 12000 + "\nend 😀"
        self.pages.update(body)
        self.assertGreater(len(self.sends), 1)
        self.assertEqual(sum(s.count("x") for s in self.sends), 12000)
        self.assertIn("start", self.sends[0])
        self.assertIn("end 😀", self.sends[-1])
        for text in self.sends:
            self.assertLessEqual(len(md_to_html(text).encode("utf-16-le")) // 2, 4096)

    def test_fenced_long_line_survives_page_split(self):
        self.pages.update("```python\n" + "x" * 12000 + "\n```")
        self.assertEqual(sum(s.count("x") for s in self.sends), 12000)
        self.assertTrue(all(len(md_to_html(s).encode("utf-16-le")) // 2 <= 4096 for s in self.sends))

    def test_restart_recovers_exact_message_ids_and_edits_without_new_sends(self):
        self.pages.update("Earlier message")
        restored = BubbleState(self.tmp.name, "native-1", "turn-1", "-100", "53")
        pages = BubblePages(restored, self.send, self.edit, _split_for_html)
        pages.update("Earlier message\n\nQuestion retained")
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(self.edits[-1][0], "1")

    def test_unconfirmed_send_is_persisted_and_never_blindly_replayed(self):
        send = mock.Mock(return_value="")
        pages = BubblePages(self.state, send, mock.Mock(), _split_for_html)
        with self.assertRaises(DeliveryUncertain):
            pages.update("A question")
        restored = BubbleState(self.tmp.name, "native-1", "turn-1", "-100", "53")
        self.assertEqual(restored.ids, [None])
        with self.assertRaises(DeliveryUncertain):
            BubblePages(restored, send, mock.Mock(), _split_for_html).update("A question")
        send.assert_called_once()

    def test_unconfirmed_edit_preserves_payload_and_fences_newer_updates_across_restart(self):
        self.pages.update("Initial")
        edit = mock.Mock(return_value=False)
        pages = BubblePages(self.state, self.send, edit, _split_for_html)
        with self.assertRaises(DeliveryUncertain):
            pages.update("Question")
        restored = BubbleState(self.tmp.name, "native-1", "turn-1", "-100", "53")
        self.assertIn("Question", restored.pending_edit["text"])
        with self.assertRaises(DeliveryUncertain):
            BubblePages(restored, self.send, edit, _split_for_html).update("Newer message")
        edit.assert_called_once()
        self.assertEqual(len(self.sends), 1)

    def test_pacing_deduplicates_unchanged_pages(self):
        self.pages.update("Original")
        self.now = 1
        self.assertFalse(self.pages.update("Updated"))
        self.now = 5
        self.pages.update("Original")
        self.assertEqual(len(self.sends), 1)
        self.assertEqual(self.edits, [])

    def test_corrupt_route_is_refused_without_overwriting_state(self):
        self.pages.update("Original")
        body = json.loads(self.state.path.read_text())
        body["topic"] = "816"
        self.state.path.write_text(json.dumps(body))
        before = self.state.path.read_bytes()
        with self.assertRaises(ValueError):
            BubbleState(self.tmp.name, "native-1", "turn-1", "-100", "53")
        self.assertEqual(before, self.state.path.read_bytes())


class MediaOnlyTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("fixture_send", Path(__file__).parents[1] / "claude-relay-send.py")
        self.send = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.send)

    def test_plain_final_is_not_duplicated_outside_bubble(self):
        with mock.patch.object(self.send, "deliver") as deliver:
            self.assertTrue(self.send.deliver_with_media("Final is already in bubble", "", media_only=True))
        deliver.assert_not_called()

    def test_images_still_attach_without_repeating_final_prose(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "image.png"
            source.write_bytes(b"synthetic-image")
            with mock.patch.object(self.send, "deliver") as deliver, \
                    mock.patch.object(self.send, "tg_send_media", return_value="1") as attach:
                result = self.send.deliver_with_media(f"Done\n\n![Diagram]({source})", folder, media_only=True)
            self.assertTrue(result)
            deliver.assert_not_called()
            self.assertEqual(attach.call_count, 1)
            self.assertEqual(attach.call_args.args[1], "Diagram")

    def test_edit_transport_requires_matching_positive_ack(self):
        transport = object.__new__(self.send._WS)
        transport.ok, transport.bot, transport._n = True, None, 0
        transport.proc = mock.Mock()
        transport._line = mock.Mock(side_effect=['{"reqid":"other","ok":true}', '{"reqid":"e1","ok":true}'])
        self.assertTrue(transport.edit_confirmed("1", "Update"))
        payload = json.loads(transport.proc.stdin.write.call_args.args[0])
        self.assertEqual(payload, {"op": "edit", "mid": "1", "text": "Update", "reqid": "e1"})
        transport._line = mock.Mock(return_value='{"reqid":"e2","ok":false}')
        self.assertFalse(transport.edit_confirmed("1", "Not accepted"))
        transport._q = queue.Queue()
        transport.proc.poll.return_value = None
        transport._line = mock.Mock(return_value=None)
        with self.assertRaises(PendingDelivery) as waiting:
            transport.edit_confirmed("1", "Unknown")
        self.assertIsNone(waiting.exception.poll())
        transport._q.put('{"reqid":"e3","ok":true}')
        self.assertTrue(waiting.exception.poll())
        self.assertEqual(transport.proc.stdin.write.call_count, 3)

    def test_send_transport_consumes_late_message_id_without_a_second_request(self):
        transport = object.__new__(self.send._WS)
        transport.ok, transport.bot, transport._n = True, None, 0
        transport.proc = mock.Mock()
        transport.proc.poll.return_value = None
        transport._q = queue.Queue()
        transport._line = mock.Mock(return_value=None)
        with self.assertRaises(PendingDelivery) as waiting:
            transport.send_confirmed("New message")
        transport._q.put('{"reqid":"s1","ok":true,"messageId":"42"}')
        self.assertEqual(waiting.exception.poll(), "42")
        self.assertEqual(transport.proc.stdin.write.call_count, 1)


if __name__ == "__main__":
    unittest.main()

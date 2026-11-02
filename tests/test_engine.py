"""Engine checks that need no window, model or network: python -m unittest discover tests"""
import json
import queue
import re
import sys
import tempfile
import threading
import types
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import companion_core as core   # noqa: E402  (sets up the bundled package paths)
import computer_skill           # noqa: E402
import llama_backend            # noqa: E402
import preview_server           # noqa: E402
import providers                # noqa: E402
from presentation_skill import _normalize   # noqa: E402

Core = core.CompanionCore


def fake_core(**fields):
    """Just the state the tested CompanionCore methods read, without starting the companion."""
    base = dict(events=queue.Queue(), action_cancel=threading.Event(), busy=False, settings={"ui_language": "ru"},
                messages=[{"role": "system", "content": "s"}], dialogue_items=[], _save_conversation=lambda: None,
                _chat_summary=lambda: "")
    base.update(fields)
    return types.SimpleNamespace(**base)


class ContextFitting(unittest.TestCase):
    def setUp(self):
        llama_backend.model_params["m"] = {"ctx_size": 2560, "compress_context": False}

    def tearDown(self):
        llama_backend.model_params.pop("m", None)

    def test_tool_descriptions_take_room_from_history(self):
        turns = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 600} for i in range(6)]
        state = fake_core(messages=[{"role": "system", "content": "s"}] + turns)
        message = {"role": "user", "content": "hi"}
        without = Core._fit_history(state, "m", {"content": "s"}, message)
        with_tools = Core._fit_history(state, "m", {"content": "s"}, message, extra=2500)
        self.assertGreater(len(without), len(with_tools))

    def test_turn_too_long_for_the_budget_is_not_sent(self):
        state = fake_core(messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "x" * 50_000}])
        self.assertEqual(Core._fit_history(state, "m", {"content": "s"}, {"role": "user", "content": "hi"}), [])


class Presentation(unittest.TestCase):
    def test_slide_without_points_becomes_a_section(self):
        slides = _normalize([{"title": "A", "layout": "cards", "bullets": []}])
        self.assertEqual(slides[0]["layout"], "section")

    def test_points_written_as_text_and_too_many_points(self):
        slides = _normalize([{"title": "A", "content": "- one\n- two"}, {"title": "B", "bullets": [str(i) for i in range(12)]}])
        self.assertEqual(slides[0]["bullets"], ["one", "two"])
        self.assertEqual(len(slides[1]["bullets"]), 8)


class ComputerCommands(unittest.TestCase):
    def test_unknown_command_lists_the_real_ones(self):
        with self.assertRaisesRegex(ValueError, "Команды «build_game» нет. Доступны: .*create_file"):
            computer_skill.execute_computer_action({"computer_action": "build_game"})

    def test_invented_names_map_to_real_commands(self):
        self.assertEqual(computer_skill._ACTION_ALIASES["save_file"], "write_file")
        self.assertEqual(computer_skill._ACTION_ALIASES["mkdir"], "create_folder")
        self.assertTrue(set(computer_skill._ACTION_ALIASES.values()) <= set(computer_skill.COMPUTER_ACTIONS))

    def test_write_file_rewrites_only_what_this_request_made(self):
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder) / "old.txt"
            old.write_text("mine", encoding="utf-8")
            created = []
            computer_skill._file_action("write_file", {"path": str(Path(folder) / "game.js"), "content": "a"}, created)
            computer_skill._file_action("write_file", {"path": str(Path(folder) / "game.js"), "content": "b"}, created)
            self.assertEqual((Path(folder) / "game.js").read_text(encoding="utf-8"), "b")
            with self.assertRaisesRegex(ValueError, "нельзя перезаписать"):
                computer_skill._file_action("write_file", {"path": str(old), "content": "x"}, created)
            self.assertEqual(old.read_text(encoding="utf-8"), "mine")

    def test_undo_deletes_only_unchanged_files_and_empty_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            created = []
            game = Path(folder) / "Game"
            computer_skill._file_action("create_folder", {"path": str(game)}, created)
            computer_skill._file_action("create_file", {"path": str(game / "a.js"), "content": "1"}, created)
            computer_skill._file_action("create_file", {"path": str(game / "b.js"), "content": "2"}, created)
            record = Core._undo_record(created)
            (game / "b.js").write_text("changed by the user", encoding="utf-8")
            removed, kept = Core.undo_files(record)
            self.assertFalse((game / "a.js").exists())
            self.assertTrue((game / "b.js").exists())
            self.assertTrue(game.exists())   # still holds the changed file
            self.assertIn(str(game / "b.js"), kept)

    def test_making_something_counts_as_asking_for_files(self):
        state = fake_core()
        state._run_computer_action = lambda item, *_: "ok"
        state.tool_browser = lambda: None
        action = {"computer_action": "create_folder", "path": "C:/x"}
        self.assertEqual(Core._execute_computer_actions(state, action, None, None, "сделай клон майнкрафта"), "ok")
        with self.assertRaisesRegex(ValueError, "не просил"):
            Core._execute_computer_actions(state, action, None, None, "как дела")


class ComputerReport(unittest.TestCase):
    def test_stop_reason_goes_out_as_an_error_and_steps_are_listed(self):
        state = fake_core(settings={"ui_language": "en"}, _without_commands=lambda text: text)
        with mock.patch.object(core, "model_chat", side_effect=RuntimeError("offline")):
            text = Core._computer_report(state, "m", [], ["create_file C:/g/index.html → done"], "", "stopped")
        self.assertEqual(state.events.get_nowait(), ("error", "stopped"))
        self.assertIn("What was done:", text)
        self.assertIn("index.html", text)


class EditingMessages(unittest.TestCase):
    def test_cut_removes_the_message_and_everything_after_it(self):
        items = [{"role": "user", "text": "a"}, {"role": "assistant", "text": "1"}, {"role": "system", "text": "#"},
                 {"role": "user", "text": "b"}, {"role": "assistant", "text": "2"}]
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "a"}, {"role": "assistant", "content": "1"},
                    {"role": "user", "content": "b"}, {"role": "assistant", "content": "2"}]
        state = fake_core(dialogue_items=list(items), messages=list(messages))
        self.assertEqual(Core.cut_history_at(state, 3), ("b", []))
        self.assertEqual(len(state.dialogue_items), 3)
        self.assertEqual(state.messages[-1]["content"], "1")

    def test_message_already_folded_into_the_summary_is_refused(self):
        items = [{"role": "user", "text": "a"}, {"role": "assistant", "text": "1"}, {"role": "user", "text": "b"}]
        state = fake_core(dialogue_items=items, messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "b"}])
        self.assertIsNone(Core.cut_history_at(state, 0))


class SavedErrors(unittest.TestCase):
    def setUp(self):   # the window module is a .pyw file, so it is loaded by path
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader("web_companion", str(ROOT / "app" / "web_companion.pyw"))
        spec = importlib.util.spec_from_loader("web_companion", loader)
        self.web = importlib.util.module_from_spec(spec)
        loader.exec_module(self.web)

    def test_error_line_is_recorded_in_the_active_chat(self):
        recorded = []
        state = types.SimpleNamespace(active_chat_id="a", _record=lambda role, text: recorded.append((role, text)))
        self.web.WebCompanion._show_error(state, "a", "boom")
        self.assertEqual(recorded, [("error", "boom")])

    def test_error_line_goes_to_a_background_chat(self):
        appended = []
        state = types.SimpleNamespace(active_chat_id="a", _changed=lambda: None,
                                      append_to_chat=lambda chat, role, text: appended.append((chat, role, text)))
        self.web.WebCompanion._show_error(state, "b", "boom")
        self.assertEqual(appended, [("b", "error", "boom")])


class ThinkingLevels(unittest.TestCase):
    def test_effort_levels_in_round_brackets(self):
        template = "{%- if reasoning_effort not in ('xhigh', 'medium', 'low') %}{%- set e = reasoning_effort|default('xhigh') %}"
        self.assertEqual(llama_backend.effort_levels(template), (["low", "medium", "xhigh"], "xhigh"))

    def test_switch_only_template_gets_budget_levels(self):
        with mock.patch.object(llama_backend, "_template", return_value="{% if enable_thinking %}<think>{% endif %}"), \
                mock.patch.object(llama_backend, "model_files", return_value={"q": (Path("q.gguf"), None)}):
            self.assertEqual(llama_backend.thinking_modes("q"), ([False, "low", "medium", "high"], "high"))

    def test_claude_generations(self):
        self.assertEqual(providers.thinking_modes("anthropic:claude-opus-5-5")[0][0], "low")   # cannot be switched off
        self.assertIn(False, providers.thinking_modes("anthropic:claude-sonnet-5-5")[0])
        self.assertEqual(providers._claude_thinking("claude-haiku-4-5")[2], "budget")
        self.assertEqual(providers.thinking_modes("anthropic:claude-3-5-haiku-20241022"), ([], None))


class ProviderRequests(unittest.TestCase):
    def body(self, name, think):
        sent = []

        def capture(request, timeout=0):
            sent.append(json.loads(request.data))
            raise OSError("captured")
        with mock.patch.object(providers.urllib.request, "urlopen", capture), \
                mock.patch.object(providers, "settings_of", lambda p: {"enabled": True, "url": providers.PROVIDERS[p]["url"], "key": "k"}):
            try:
                providers.chat(name, [{"role": "user", "content": "hi"}], sampling={"temperature": 0.7}, think=think)
            except Exception:
                pass
        return sent[-1]

    def test_claude_effort_and_no_temperature_on_new_models(self):
        body = self.body("anthropic:claude-opus-5-5", "high")
        self.assertEqual(body["output_config"], {"effort": "high"})
        self.assertNotIn("temperature", body)
        self.assertEqual(self.body("anthropic:claude-sonnet-5-5", False)["thinking"], {"type": "between_tools"})

    def test_old_claude_keeps_temperature_and_gets_a_budget(self):
        self.assertEqual(self.body("anthropic:claude-3-5-haiku-20241022", "__auto__")["temperature"], 0.7)
        body = self.body("anthropic:claude-haiku-4-5", "medium")
        self.assertEqual(body["thinking"]["budget_tokens"], 8192)
        self.assertGreater(body["max_tokens"], 8192)

    def test_openai_reasoning_model(self):
        body = self.body("openai:gpt-5.1", "low")
        self.assertEqual(body["reasoning_effort"], "low")
        self.assertNotIn("temperature", body)


class Translations(unittest.TestCase):
    def test_every_entry_is_complete(self):
        data = json.loads((ROOT / "modern-ui/src/i18n/strings.json").read_text(encoding="utf-8"))
        for key, values in data.items():
            self.assertEqual(len(values), 3, key)
            for text in values:
                self.assertTrue(text.strip(), key)
                self.assertEqual(sorted(re.findall(r"\{\d\}", key)), sorted(re.findall(r"\{\d\}", text)), key)


class Preview(unittest.TestCase):
    def test_serves_the_page_from_its_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            page = Path(folder) / "index.html"
            page.write_text("<h1>ok</h1>", encoding="utf-8")
            try:
                with urllib.request.urlopen(preview_server.url_for(page), timeout=5) as response:
                    self.assertEqual(response.read(), b"<h1>ok</h1>")
            finally:
                preview_server.stop_all()


if __name__ == "__main__":
    unittest.main()

import copy
import importlib.machinery
import importlib.util
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.chat import engine as core
from app.chat import knowledge


def wait_for_index(index, scope):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = index.status(scope)
        if not status["indexing"]:
            return status
        time.sleep(0.02)
    raise AssertionError("The index did not finish")


class KnowledgeBranches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("piven_knowledge_window", str(ROOT / "app" / "window" / "main.pyw"))
        cls.web = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(cls.web)

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name).resolve()
        self.docs = self.data / "docs"
        self.docs.mkdir()
        self.doc = self.docs / "manual.md"
        self.doc.write_text("\n# Ротор\nВыдержка ротора составляет 17 секунд.\n# Осмотр\nОсматривай кожух ежемесячно.\n", encoding="utf-8")
        self.index = knowledge.Knowledge(self.data)
        self.addCleanup(self.index._db.close)
        self.index.start("main", self.docs)
        self.assertEqual(wait_for_index(self.index, "main")["files"], 1)

    def companion(self):
        app = core.CompanionCore()
        app.knowledge = self.index
        app._state_lock = threading.RLock()
        app._busy_chats = set()
        app._chat_cancels, app._live_messages, app._live_turns = {}, {}, {}
        app.running = False
        app.events = core.ChatEvents(app)
        app.active_chat_id = "main"
        app.settings = {"system_prompt": "Test", "model": "custom:test", "memory_enabled": False, "tools_enabled": False}
        app.selected_model = "custom:test"
        app._messages = [{"role": "system", "content": "Test"}]
        app.dialogue_items = []
        app.chats = [{"id": "main", "title": "Проект", "model": "custom:test", "titled": True, "items": [], "messages": []}]
        app._conversation_save_lock = threading.Lock()
        app._conversation_save_generation = 0
        app._loading_chat = False
        app._changed = lambda: None
        app._schedule_conversation_write = lambda: app._write_conversation_now(synchronous=True)
        return app

    def test_index_is_scoped_persistent_and_refreshed_when_documents_change(self):
        source, = self.index.search("main", "выдержка ротора")
        self.assertEqual((source["path"], source["section"], source["start"], source["end"]), ("manual.md", "Ротор", 2, 3))
        self.assertEqual(knowledge.source_path(source), self.doc)
        self.assertNotIn(str(self.docs), knowledge.prompt_block([source]))
        self.assertEqual(self.index.search("unrelated", "выдержка ротора"), [])

        reopened = knowledge.Knowledge(self.data)
        self.addCleanup(reopened._db.close)
        self.assertEqual(reopened.search("main", "выдержка ротора"), [source])
        self.doc.write_text("# Ротор\nВыдержка ротора теперь 42 секунды.\n", encoding="utf-8")
        reopened.start("main", self.docs)
        self.assertEqual(wait_for_index(reopened, "main")["files"], 1)
        self.assertIn("42 секунды", reopened.search("main", "выдержка ротора")[0]["text"])
        reopened.remove("main")
        self.assertEqual(self.index.search("main", "выдержка ротора"), [])

    def test_branch_is_a_saved_snapshot_and_does_not_copy_the_undo_action_or_later_summary(self):
        app = self.companion()
        app.chats[0].update(code_on=True, code_root=str(self.data), code_mode="ask", summary="Later events")
        sources = self.index.search("main", "выдержка ротора")
        app.dialogue_items = [
            {"role": "user", "text": "Сколько секунд?", "files": [str(self.doc)]},
            {"role": "assistant", "text": "17 секунд [K1].", "created": 1789048860.5, "sources": sources, "undo": [{"path": "file"}]},
            {"role": "code", "text": "Old tool state"},
            {"role": "user", "text": "This must stay in the original."},
        ]
        app.messages.extend([{"role": item["role"], "content": item["text"]} for item in app.dialogue_items if item["role"] != "code"])
        path = self.data / "conversation.json"
        with mock.patch.object(core, "CONVERSATION_PATH", path):
            self.assertIsNone(app.fork_chat("main", 1, "outdated"))
            branch = app.fork_chat("main", 1, "17 секунд [K1].")
            self.assertEqual(app.active_chat_id, branch["id"])
            self.assertEqual(branch["branch_from"], "main")
            self.assertEqual(branch["code_root"], str(self.data))
            self.assertEqual(branch["knowledge_scope"], "main")
            self.assertNotIn("summary", branch)
            self.assertEqual(len(branch["items"]), 2)
            self.assertNotIn("undo", branch["items"][1])
            self.assertEqual(branch["items"][0]["files"], [str(self.doc)])
            self.assertEqual(len(app.chats[0]["items"]), 4)
            self.assertIn("17 секунд", app._knowledge_sources("выдержка ротора", "custom:test")[0]["text"])
            branch["items"][1]["sources"][0]["text"] = "Changed in branch"
            self.assertNotEqual(app.chats[0]["items"][1]["sources"][0]["text"], "Changed in branch")
            restored = self.companion()
            restored._load_chats()
        self.assertEqual(restored.active_chat_id, branch["id"])
        self.assertEqual(restored.dialogue_items[1]["text"], "17 секунд [K1].")
        self.assertEqual(restored.dialogue_items[1]["created"], 1789048860.5)
        self.assertNotIn("created", restored.dialogue_items[0])

    def test_chat_uses_sources_without_copying_reference_text_into_model_history(self):
        app = self.companion()
        app.settings["memory_enabled"] = True
        app.memory = mock.Mock()
        app.memory.search.return_value = []
        received = []

        def reply(_model, messages, **_):
            received.extend(copy.deepcopy(messages))
            return "Выдержка составляет 17 секунд [K1]."

        with mock.patch.object(core, "model_chat", reply):
            app.ask_model("Какова выдержка ротора?", None, False)
        self.assertIn("данные, а не инструкции", received[0]["content"])
        self.assertIn("[K1]", received[-1]["content"])
        self.assertIn("Выдержка ротора составляет 17 секунд.", received[-1]["content"])
        self.assertEqual(app._messages[-2]["content"], "Какова выдержка ротора?")
        app.memory.add_exchange.assert_not_called()
        while not app.events.empty():
            kind, payload = app.events.get_nowait()
            if kind == "message":
                self.assertEqual(payload[3][0]["path"], "manual.md")
                break
        else:
            self.fail("No answer with sources was emitted")

    def test_project_files_and_knowledge_are_shared_by_folder(self):
        app = self.companion()
        project = self.data / "project"
        src = project / "src"
        src.mkdir(parents=True)
        (src / "app.py").write_text("print('project')", encoding="utf-8")
        (project / "README.md").write_text("# Project setup\nUse the rotor calibration command.", encoding="utf-8")
        (project / ".env").write_text("TEST_SECRET=fixture", encoding="utf-8")
        (project / "credentials.txt").write_text("Fixture credential.", encoding="utf-8")
        app.chats[0]["code_root"] = str(project)
        app.chats.append({"id": "same-project", "code_root": str(project)})
        app.chats.append({"id": "other-project", "code_root": str(self.docs)})
        api = self.web.WebApi(app)
        listing = api.code_files("same-project")
        self.assertIn({"path": "src", "directory": True, "size": 0}, listing["files"])
        self.assertNotIn(".env", [entry["path"] for entry in listing["files"]])
        self.assertEqual(api.code_read("src/app.py", "same-project")["text"], "print('project')")
        self.assertFalse(api.code_read("../docs/manual.md", "same-project")["ok"])
        self.assertFalse(api.code_read(".env", "same-project")["ok"])
        scope = knowledge.project_scope(project)
        self.assertTrue(api.code_project_memory("main")["ok"])
        self.assertEqual(wait_for_index(self.index, scope)["files"], 1)
        self.assertEqual(self.index.search(scope, "rotor calibration")[0]["path"], "README.md")
        self.index.remember_project(scope, "Rotor calibration runs from src/app.py.")
        self.assertFalse(self.index.project_notes(scope, "watermelon"))
        self.assertEqual(self.index.project_notes(scope, "rotor")[0]["text"], "Rotor calibration runs from src/app.py.")
        note, = api.code_project_memory("same-project")["notes"]
        self.assertTrue(api.code_project_memory("other-project", "forget", note["id"])["ok"])
        self.assertEqual(api.code_project_memory("main")["notes"], [note])
        self.assertEqual(api.code_project_memory("same-project", "forget", note["id"])["notes"], [])

    def test_plan_updates_replace_one_card_in_the_correct_chat(self):
        import json

        app = self.companion()
        app._code_plans = {}
        app._record = app.record_dialogue_item
        other = {"id": "other", "items": []}
        app.chats.append(other)
        active = {"kind": "plan", "planId": "task-one", "items": [{"text": "Check the page", "status": "in_progress"}]}
        updated = {**active, "items": [{"text": "Check the page", "status": "done"}]}
        record = self.web.WebCompanion._record_code_plan
        with mock.patch.object(core, "CONVERSATION_PATH", self.data / "conversation.json"):
            record(app, "main", active)
            app.record_dialogue_item("code", '{"kind":"command"}')
            record(app, "main", updated)
            record(app, "other", {**active, "planId": "task-two"})
            record(app, "other", {**updated, "planId": "task-two"})
        self.assertEqual(len(app.dialogue_items), 2)
        self.assertEqual(json.loads(app.dialogue_items[0]["text"]), updated)
        self.assertEqual(len(other["items"]), 1)
        self.assertEqual(json.loads(other["items"][0]["text"])["items"][0]["status"], "done")
        self.assertEqual(app._code_plans["main"], updated)

    def test_source_bridge_returns_only_the_excerpt_from_the_requested_message(self):
        app = self.companion()
        app.dialogue_items = [{"role": "assistant", "sources": self.index.search("main", "выдержка ротора")}]
        api = self.web.WebApi(app)
        self.assertIn("17 секунд", api.knowledge_excerpt("main", 0, 1, "manual.md")["text"])
        self.assertFalse(api.knowledge_excerpt("another", 0, 1, "manual.md")["ok"])
        self.assertFalse(api.knowledge_excerpt("main", 0, 1, "wrong.md")["ok"])

    def test_new_chat_does_not_reuse_an_empty_chat_with_a_configured_knowledge_folder(self):
        app = self.companion()
        with mock.patch.object(core, "CONVERSATION_PATH", self.data / "conversation.json"):
            self.assertTrue(self.web.WebApi(app).new_chat()["ok"])
        self.assertNotEqual(app.active_chat_id, "main")
        self.assertFalse(self.index.configured(app.active_chat_id))

    def test_new_chat_does_not_reuse_an_empty_chat_with_a_draft(self):
        app = self.companion()
        self.index.remove("main")
        with mock.patch.object(core, "CONVERSATION_PATH", self.data / "conversation.json"):
            self.assertTrue(self.web.WebApi(app).new_chat(["main"])["ok"])
        self.assertNotEqual(app.active_chat_id, "main")
        self.assertEqual(len(app.chats), 2)

    def test_sidebar_creates_a_branch_from_the_latest_turn_of_an_inactive_chat(self):
        app = self.companion()
        origin = app.chats[0]
        origin["items"] = [
            {"role": "user", "text": "Сколько секунд?"},
            {"role": "assistant", "text": "17 секунд [K1].", "sources": self.index.search("main", "выдержка ротора")},
            {"role": "system", "text": "Служебное сообщение"},
        ]
        app.dialogue_items = origin["items"]
        api = self.web.WebApi(app)
        with mock.patch.object(core, "CONVERSATION_PATH", self.data / "conversation.json"):
            other = app.create_chat()
            app.record_dialogue_item("user", "Другой разговор")
            app._busy_chats.add("main")
            self.assertFalse(api.fork_chat("main")["ok"])
            self.assertEqual(app.active_chat_id, other["id"])
            app._busy_chats.remove("main")
            self.assertTrue(api.fork_chat("main")["ok"])
        branch = app._active_chat()
        self.assertEqual(branch["branch_from"], "main")
        self.assertEqual(branch["knowledge_scope"], "main")
        self.assertEqual([item["text"] for item in branch["items"]], ["Сколько секунд?", "17 секунд [K1]."])
        self.assertEqual(branch["items"][-1]["sources"][0]["path"], "manual.md")
        self.assertEqual(other["items"][0]["text"], "Другой разговор")
        self.assertGreater(other["items"][0]["created"], 0)

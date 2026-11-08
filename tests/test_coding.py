import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.chat import coding as agent_module
from app.chat import commands
from app.chat import engine as core
from app.tools import coding


def make_tools(root, **fields):
    data = Path(root).parent / "data"
    data.mkdir(exist_ok=True)
    return coding.CodeTools(root, ROOT, data, **fields)


class FileTools(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "project"
        self.root.mkdir()
        self.tools = make_tools(self.root)

    def test_write_makes_folders_and_reports_syntax_errors(self):
        self.assertIn("Wrote src/a.py", self.tools.run("write_file", {"path": "src/a.py", "content": "print(1)\n"}))
        self.assertEqual((self.root / "src" / "a.py").read_text(encoding="utf-8"), "print(1)\n")
        self.assertIn("Syntax error at line 1", self.tools.run("write_file", {"path": "b.py", "content": "def (\n"}))
        self.assertIn("JSON error", self.tools.run("write_file", {"path": "c.json", "content": "{"}))

    def test_a_long_file_can_be_written_in_parts(self):
        self.tools.run("write_file", {"path": "a.txt", "content": "one\n"})
        self.tools.run("write_file", {"path": "a.txt", "content": "two\n", "append": True})
        self.assertEqual((self.root / "a.txt").read_text(encoding="utf-8"), "one\ntwo\n")

    def test_edit_replaces_exact_and_unique_text(self):
        path = self.root / "a.txt"
        path.write_text("alpha\nbeta\nbeta\n", encoding="utf-8")
        self.assertIn("occurs 2 times", self.tools.run("edit_file", {"path": "a.txt", "old_text": "beta", "new_text": "x"}))
        self.assertIn("Edited", self.tools.run("edit_file", {"path": "a.txt", "old_text": "alpha\nbeta", "new_text": "gamma"}))
        self.assertEqual(path.read_text(encoding="utf-8"), "gamma\nbeta\n")
        self.assertIn("Edited", self.tools.run("edit_file", {"path": "a.txt", "old_text": "beta", "new_text": "z", "replace_all": True}))

    def test_edit_forgives_indentation_and_keeps_windows_line_ends(self):
        path = self.root / "a.py"
        path.write_bytes(b"def f():\r\n    return 1\r\n")
        self.assertIn("Edited", self.tools.run("edit_file", {"path": "a.py", "old_text": "def f():\n  return 1", "new_text": "def f():\n    return 2"}))
        self.assertEqual(path.read_bytes(), b"def f():\r\n    return 2\r\n")

    def test_a_failed_edit_shows_the_closest_place(self):
        (self.root / "a.txt").write_text("hello world\nsecond\n", encoding="utf-8")
        reply = self.tools.run("edit_file", {"path": "a.txt", "old_text": "hello wurld", "new_text": "x"})
        self.assertIn("not found", reply)
        self.assertIn("1|hello world", reply)

    def test_read_numbers_lines_and_pages(self):
        (self.root / "a.txt").write_text("\n".join(f"line{i}" for i in range(1, 11)), encoding="utf-8")
        reply = self.tools.run("read_file", {"path": "a.txt", "offset": 3, "limit": 2})
        self.assertIn("3|line3", reply)
        self.assertIn("read further with offset 5", reply)

    def test_the_project_folder_is_a_wall(self):
        for path in ("../out.txt", "C:/Windows/out.txt", "..\\..\\out.txt"):
            self.assertIn("outside the project folder", self.tools.run("write_file", {"path": path, "content": "x"}))
        self.assertFalse((self.root.parent / "out.txt").exists())

    def test_secret_files_are_not_touched(self):
        (self.root / ".env").write_text("KEY=1", encoding="utf-8")
        self.assertIn("secrets", self.tools.run("read_file", {"path": ".env"}))
        self.assertIn("secrets", self.tools.run("write_file", {"path": ".env", "content": ""}))
        self.assertIn("No matches", self.tools.run("search", {"pattern": "KEY"}))

    def test_search_and_list_skip_ignored_folders(self):
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "x.js").write_text("needle", encoding="utf-8")
        (self.root / "a.js").write_text("needle here", encoding="utf-8")
        self.assertEqual(self.tools.run("search", {"pattern": "needle"}), "a.js:1: needle here")
        self.assertNotIn("node_modules", self.tools.run("list_files", {}))

    def test_a_missing_file_suggests_similar_names(self):
        (self.root / "game.js").write_text("", encoding="utf-8")
        self.assertIn("game.js", self.tools.run("read_file", {"path": "gam.js"}))

    def test_undo_restores_edits_removes_new_files_and_brings_deleted_back(self):
        old = self.root / "old.txt"
        gone = self.root / "gone.txt"
        old.write_text("before", encoding="utf-8")
        gone.write_text("still here", encoding="utf-8")
        self.tools.run("write_file", {"path": "old.txt", "content": "after"})
        self.tools.run("write_file", {"path": "new/new.txt", "content": "new"})
        self.tools.run("delete_file", {"path": "gone.txt"})
        self.assertFalse(gone.exists())
        changed = {Path(row["path"]).name: row["state"] for row in self.tools.finish()}
        self.assertEqual(changed, {"old.txt": "edited", "new.txt": "created", "gone.txt": "deleted"})
        restored, kept = coding.restore_checkpoint(self.tools.checkpoint)
        self.assertEqual(kept, [])
        self.assertEqual(len(restored), 3)
        self.assertEqual(old.read_text(encoding="utf-8"), "before")
        self.assertEqual(gone.read_text(encoding="utf-8"), "still here")
        self.assertFalse((self.root / "new").exists())

    def test_undo_leaves_a_file_the_user_changed_later(self):
        self.tools.run("write_file", {"path": "a.txt", "content": "agent"})
        self.tools.finish()
        (self.root / "a.txt").write_text("the user's text", encoding="utf-8")
        restored, kept = coding.restore_checkpoint(self.tools.checkpoint)
        self.assertEqual((restored, len(kept)), ([], 1))
        self.assertEqual((self.root / "a.txt").read_text(encoding="utf-8"), "the user's text")

    def test_outline_lists_declarations_with_lines(self):
        (self.root / "a.js").write_text("const A = 1;\n\nfunction draw(x) {\n  let inner = 2;\n}\nclass Game {}\n", encoding="utf-8")
        reply = self.tools.run("outline", {"path": "a.js"})
        for row in ("1: const A", "3: function draw", "6: class Game"):
            self.assertIn(row, reply)
        (self.root / "b.py").write_text("import os\n\nclass A:\n    def run(self):\n        pass\n", encoding="utf-8")
        self.assertIn("4: def run", self.tools.run("outline", {"path": "b.py"}))

    def test_other_argument_names_are_understood(self):
        (self.root / "a.txt").write_text("one", encoding="utf-8")
        self.assertIn("Edited", self.tools.run("edit_file", {"file_path": "a.txt", "old_string": "one", "new_string": "two"}))
        self.assertEqual((self.root / "a.txt").read_text(encoding="utf-8"), "two")

    def test_broken_arguments_explain_what_to_do(self):
        self.assertIn("smaller parts", self.tools.run("write_file", {"_raw": "{"}))


class Commands(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "project"
        self.root.mkdir()
        self.asked = []

    def tools(self, answer, **fields):
        def ask(command, reason, can_trust, kind="command"):
            self.asked.append((command, can_trust))
            return answer
        return make_tools(self.root, ask=ask, **fields)

    def test_policy(self):
        root = str(self.root)
        self.assertEqual(coding.command_policy('cd "C:\\My Projects\\game" && mkdir js', "C:\\My Projects\\game")[0], "normal")
        self.assertEqual(coding.command_policy('type "C:\\My Projects\\other\\a.txt"', "C:\\My Projects\\game")[0], "ask")
        cases = {"format c:": "refuse", "format /q d:": "refuse", "FORMAT C: /fs:ntfs": "refuse", "format-volume -DriveLetter C": "refuse", "diskpart": "refuse", "rd /s /q c:\\": "refuse", "del /s /q c:\\*": "refuse",
                 "Remove-Item -Recurse -Force C:\\": "refuse", "rm -rf /": "refuse", "reg delete HKCU\\x": "refuse", "shutdown /s": "refuse", "type %LOCALAPPDATA%\\OllamaCompanion\\settings.json": "refuse",
                 "node --check a.js && node --check b.js && echo ALL_OK": "safe", "node --check a.js && python game.py": "normal", "node --check a.js & python game.py": "normal", "echo x > a.txt": "normal",
                 "python -m unittest": "safe", "git status": "safe", "node --check a.js": "safe", "pytest -q": "safe",
                 "python game.py": "normal", "npm run dev": "normal", "git status & del a": "ask",
                 "pip install pygame": "ask", "python -m pip install x": "ask", "npm install": "ask", "git push": "ask", "del a.txt": "ask", "curl http://x": "ask",
                 "type C:\\Windows\\win.ini": "ask", "type ..\\x": "ask", f"python {root}\\a.py": "normal"}
        for command, verdict in cases.items():
            self.assertEqual(coding.command_policy(command, root)[0], verdict, command)

    def test_runs_in_the_project_and_returns_output_and_exit_code(self):
        tools = self.tools("once")
        (self.root / "a.py").write_text("import os\nprint('привет', os.getcwd())\nraise SystemExit(3)", encoding="utf-8")
        reply = tools.run("run_command", {"command": "python a.py"})
        self.assertIn("Exit code 3", reply)
        self.assertIn("привет", reply)
        self.assertIn(self.root.name, reply)

    def test_denied_command_does_not_run_and_the_model_is_told(self):
        tools = self.tools(False)
        reply = tools.run("run_command", {"command": "echo made> made.txt"})
        self.assertIn("did not allow", reply)
        self.assertFalse((self.root / "made.txt").exists())

    def test_trust_stops_the_questions_but_not_for_risky_commands(self):
        saved = []
        tools = self.tools("project", on_trust=lambda: saved.append(True))
        tools.run("run_command", {"command": "python -c print(1)"})
        self.assertEqual(saved, [True])
        tools.run("run_command", {"command": "python -c print(2)"})
        self.assertEqual(len(self.asked), 1)
        tools.run("run_command", {"command": "pip install nothing-at-all-here --dry-run"})
        self.assertEqual(len(self.asked), 2)
        self.assertFalse(self.asked[1][1])

    def test_modes_decide_what_is_asked(self):
        for mode, expected in (("ask", 2), ("edits", 2), ("free", 0)):
            self.asked.clear()
            tools = self.tools(True, mode=mode)
            for command in ("python game.py", "pip install pygame", "python -m unittest"):
                tools._permitted(command)
            self.assertEqual(len(self.asked), expected, mode)

    def test_edits_ask_only_in_the_ask_mode(self):
        tools = self.tools(True, mode="ask")
        tools.run("write_file", {"path": "a.txt", "content": "one\n"})
        self.assertEqual(len(self.asked), 1)
        self.asked.clear()
        tools = self.tools(True, mode="edits")
        tools.run("write_file", {"path": "b.txt", "content": "one\n"})
        self.assertEqual(self.asked, [])

    def test_a_refused_edit_changes_nothing(self):
        tools = self.tools(False, mode="ask")
        reply = tools.run("write_file", {"path": "a.txt", "content": "one\n"})
        self.assertIn("did not allow", reply)
        self.assertFalse((self.root / "a.txt").exists())

    def test_accepting_edits_stops_the_questions(self):
        switched = []
        tools = self.tools("project", mode="ask", on_edits=lambda: switched.append(True))
        tools.run("write_file", {"path": "a.txt", "content": "one\n"})
        tools.run("write_file", {"path": "b.txt", "content": "two\n"})
        self.assertEqual(switched, [True])
        self.assertEqual(len(self.asked), 1)

    def test_plan_mode_changes_nothing(self):
        tools = self.tools(True, mode="plan")
        names = [spec["function"]["name"] for spec in tools.specs()]
        for name in ("write_file", "edit_file", "move_file", "delete_file", "check_window"):
            self.assertNotIn(name, names)
        self.assertIn("read_file", names)
        self.assertIn("Plan mode", tools.run("write_file", {"path": "a.txt", "content": "one\n"}))
        self.assertFalse((self.root / "a.txt").exists())
        self.assertIn("Plan mode", tools.run("run_command", {"command": "python -c print(1)"}))
        self.assertEqual(self.asked, [])

    def test_free_mode_still_refuses_the_forbidden(self):
        tools = self.tools(True, mode="free")
        for command in ("format c:", "shutdown /s", "reg delete HKCU\\x", "type %LOCALAPPDATA%\\OllamaCompanion\\settings.json"):
            with self.assertRaises(ValueError):
                tools._permitted(command)
        self.assertEqual(self.asked, [])

    def test_the_agent_cannot_leave_the_project_in_any_mode(self):
        from unittest import mock
        other = "D:\\somewhere\\companion-mod"
        for mode in ("ask", "edits", "free"):
            tools = self.tools(True, mode=mode)
            for command in (f'cd /d "{other}" && python a.py', f"cd {other}", "cd ..", f"pushd {other}", f'mkdir "{other}\\x"', f"echo hi > {other}\\a.txt", f"copy a.txt {other}\\a.txt"):
                with mock.patch.object(coding.tempfile, "gettempdir", return_value="D:\\temp"), self.assertRaises(ValueError, msg=command) as caught:
                    tools._permitted(command)
                self.assertIn("outside the project", str(caught.exception))
        self.assertEqual(self.asked, [])

    def test_commands_inside_the_project_are_not_stopped(self):
        tools = self.tools(True, mode="free")
        for command in (f'cd /d "{self.root}" && python a.py', "cd src && python a.py", f"mkdir {self.root}\\sub", "where java", "copy C:\\tools\\a.txt b.txt"):
            self.assertTrue(tools._permitted(command), command)

    def test_the_mode_can_change_while_the_agent_works(self):
        current = ["ask"]
        tools = self.tools(False, mode=lambda: current[0])
        self.assertFalse(tools._permitted("python game.py"))
        current[0] = "free"
        self.assertTrue(tools._permitted("pip install pygame"))
        self.assertEqual(len(self.asked), 1)
        current[0] = "nonsense"
        self.assertFalse(tools._permitted("python game.py"))

    def test_the_engine_picks_the_mode_of_a_chat(self):
        import types
        state = types.SimpleNamespace(settings={"code_trusted": ["C:\\p"]}, _save_settings=lambda: None)
        state._code_trusted = lambda root: core.CompanionCore._code_trusted(state, root)
        state._trust_project = lambda root, chat=None: core.CompanionCore._trust_project(state, root, chat)
        pick = lambda chat, root: core.CompanionCore._code_mode(state, chat, root)
        self.assertEqual(pick({}, "C:\\p"), "edits")
        self.assertEqual(pick({}, "C:\\other"), "ask")
        self.assertEqual(pick({"code_mode": "free"}, "C:\\other"), "free")
        self.assertEqual(pick({"code_mode": "plan"}, "C:\\p"), "plan")
        self.assertEqual(pick({"code_mode": "bogus"}, "C:\\p"), "edits")
        self.assertEqual(pick(None, "C:\\p"), "edits")
        state.settings["code_mode_last"] = "free"
        self.assertEqual(pick({}, "C:\\other"), "free")

    def test_chats_from_before_the_new_modes_keep_working(self):
        import types
        state = types.SimpleNamespace(settings={"code_trusted": []}, _save_settings=lambda: None)
        state._code_trusted = lambda root: core.CompanionCore._code_trusted(state, root)
        state._trust_project = lambda root, chat=None: core.CompanionCore._trust_project(state, root, chat)
        chat = {"code_mode": "project"}
        self.assertEqual(core.CompanionCore._code_mode(state, chat, "C:\\p"), "edits")
        self.assertEqual(chat["code_mode"], "edits")
        self.assertIn("C:\\p", state.settings["code_trusted"])

    def test_refused_command_is_never_asked(self):
        tools = self.tools("once")
        started = []
        tools._start = lambda command, shell: started.append(command)
        self.assertIn("not allowed", tools.run("run_command", {"command": "shutdown /s /t 3600"}))
        self.assertEqual((self.asked, started), ([], []))

    def test_timeout_stops_the_program_and_tells_about_background(self):
        tools = self.tools("once")
        (self.root / "a.py").write_text("import time\nprint('started', flush=True)\ntime.sleep(60)", encoding="utf-8")
        reply = tools.run("run_command", {"command": "python a.py", "timeout": 2})
        self.assertIn("background: true", reply)
        self.assertIn("started", reply)

    def test_background_keeps_running_until_stopped(self):
        tools = self.tools("once")
        self.addCleanup(coding.stop_jobs)
        (self.root / "a.py").write_text("import time\nprint('up', flush=True)\ntime.sleep(60)", encoding="utf-8")
        reply = tools.run("run_command", {"command": "python a.py", "background": True})
        self.assertIn("still running", reply)
        job = reply.split("id ")[1].split(" ")[0]
        self.assertIn("Still running", tools.run("command_status", {"id": job}))
        self.assertIn("Stopped", tools.run("command_status", {"id": job, "stop": True}))
        self.assertIn("no running command", tools.run("command_status", {"id": job}))

    def test_interrupt_stops_a_running_command(self):
        cancel = threading.Event()
        tools = self.tools("once", cancel=cancel)
        (self.root / "a.py").write_text("import time\ntime.sleep(60)", encoding="utf-8")
        threading.Timer(0.5, cancel.set).start()
        with self.assertRaises(InterruptedError):
            tools.run("run_command", {"command": "python a.py"})

    def test_api_keys_do_not_reach_commands(self):
        import os
        tools = self.tools("once")
        os.environ["SOME_API_KEY"] = "secret-value"
        self.addCleanup(os.environ.pop, "SOME_API_KEY")
        self.assertNotIn("secret-value", tools.run("run_command", {"command": "set"}))


class TextCalls(unittest.TestCase):
    NAMES = {"write_file", "read_file"}

    def test_known_text_forms(self):
        for text in ('<tool_call>\n{"name": "read_file", "arguments": {"path": "a"}}\n</tool_call>',
                     '```json\n{"name": "read_file", "arguments": {"path": "a"}}\n```',
                     '{"tool": "read_file", "args": {"path": "a"}}',
                     '<function=read_file><parameter=path>a</parameter></function>'):
            calls = agent_module.parse_text_calls(text, self.NAMES)
            self.assertEqual([(call["name"], call["arguments"]) for call in calls], [("read_file", {"path": "a"})], text)

    def test_other_json_and_unknown_tools_are_not_calls(self):
        for text in ('Here is the config: {"name": "game", "version": 1}', '{"name": "rm_rf", "arguments": {}}', "Just text"):
            self.assertEqual(agent_module.parse_text_calls(text, self.NAMES), [], text)

    def test_salvage_keeps_complete_lines_of_a_cut_off_write(self):
        raw = '{"path":"a.js","content":"line1\\nline2\\nli'
        self.assertEqual(agent_module.salvage_write(raw), {"path": "a.js", "content": "line1\nline2\n", "append": False})
        self.assertEqual(agent_module.salvage_write('{"path":"a.js","content":"one\\ntwo\\n\\'), {"path": "a.js", "content": "one\ntwo\n", "append": False})
        self.assertIsNone(agent_module.salvage_write('{"content":"no path\\n'))


def scripted(steps, seen=None, closing=()):
    """A model that follows a list of steps: each is text, a tool call or a list of them. closing is what it says once it has no tools."""
    steps = iter(steps)
    closing = iter(closing)

    def chat(context, specs, calls, info):
        if seen is not None:
            seen.append(json.loads(json.dumps(context)))
        step = next(steps, "All done.") if specs is not None else next(closing, "All done.")
        if isinstance(step, dict):
            step = [step]
        if isinstance(step, list):
            for index, (name, arguments) in enumerate((item["name"], item["arguments"]) for item in step):
                calls.append({"id": f"c{index}", "name": name, "arguments": arguments})
            return ""
        return step
    return chat


def call(name, **arguments):
    return {"name": name, "arguments": arguments}


class AgentLoop(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "project"
        self.root.mkdir()
        self.events = []

    def agent(self, steps, seen=None, size=16000, count=lambda text: len(text) // 3, tools=None, closing=(), **fields):
        tools = tools or make_tools(self.root, ask=lambda *args: "once")
        return agent_module.Agent(scripted(steps, seen, closing), tools, count, size, self.events.append, threading.Event(), "system", fields.pop("request", "Сделай игру"), **fields)

    def test_writes_runs_and_answers(self):
        agent = self.agent([call("write_file", path="a.py", content="print('ok')\n"), call("run_command", command="python a.py"), "Готово: a.py"])
        self.assertEqual(agent.run(), "Готово: a.py")
        self.assertTrue((self.root / "a.py").exists())
        self.assertTrue(any(item["role"] == "tool" and "Exit code 0" in item["content"] for item in agent.context))

    def test_a_model_that_only_talks_is_told_to_act(self):
        seen = []
        agent = self.agent(["Я бы сделал так...", call("write_file", path="a.py", content="print(1)\n"), call("run_command", command="python a.py"), "Готово"], seen)
        self.assertEqual(agent.run(), "Готово")
        self.assertIn("agent mode", seen[1][-1]["content"])

    def test_a_final_message_that_waits_for_a_go_ahead_does_not_end_the_work(self):
        seen = []
        agent = self.agent([
            call("write_file", path="a.py", content="print(1)\n"), call("run_command", command="python a.py"),
            "Осталось написать index.html. Скажи «пиши» — и я создам файл.",
            call("write_file", path="index.html", content="<p>1</p>\n"), call("run_command", command="python a.py"),
            "Готово: index.html"], seen)
        self.assertEqual(agent.run(), "Готово: index.html")
        self.assertTrue((self.root / "index.html").exists())
        self.assertTrue(any("Nobody will answer" in str(item.get("content")) for item in agent.context))

    def test_pushing_on_ends_when_the_model_keeps_asking(self):
        question = "Какой цвет выбрать?"
        agent = self.agent([call("write_file", path="a.py", content="print(1)\n"), call("run_command", command="python a.py")] + [question] * 8)
        self.assertEqual(agent.run(), question)

    def test_a_question_from_the_user_is_answered_without_pushing(self):
        self.assertEqual(self.agent(["Хочешь узнать больше?"], request="Что это?", may_only_answer=True).run(), "Хочешь узнать больше?")

    def test_a_lost_agent_is_sent_back_to_the_task_before_it_is_stopped(self):
        (self.root / "a.py").write_text("print(1)\n", encoding="utf-8")
        steps = [call("read_file", path="a.py", offset=index) for index in range(1, agent_module.NO_CHANGE_LIMIT + 1)]
        steps += [call("write_file", path="game.py", content="print(2)\n"), call("run_command", command="python game.py"), "Готово: game.py"]
        agent = self.agent(steps, request="Сделай игру")
        self.assertEqual(agent.run(), "Готово: game.py")
        self.assertTrue((self.root / "game.py").exists())
        self.assertFalse(agent.closing)
        self.assertTrue(any("The task is still: Сделай игру" in str(item.get("content")) for item in agent.context))

    def test_the_window_usage_is_reported_while_the_agent_works(self):
        seen = []
        agent = self.agent([call("write_file", path="a.py", content="print(1)\n" * 50), call("run_command", command="python a.py"), "Готово"], on_usage=lambda parts, turns: seen.append((dict(parts), turns)))
        agent.run()
        self.assertGreaterEqual(len(seen), 3)
        first, last = seen[0][0], seen[-1][0]
        self.assertGreater(first["system"], 0)
        self.assertGreater(first["tools"], 0)
        self.assertGreater(last["history"], first["history"])
        self.assertGreater(seen[-1][1], seen[0][1])

    def test_messages_written_while_working_are_read_before_the_next_step(self):
        seen, inbox = [], []
        agent = self.agent([call("write_file", path="a.py", content="print(1)\n"), call("run_command", command="python a.py"), "Готово", "Сделал и цвет"], seen, incoming=lambda: [inbox.pop(0)] if inbox else [])
        original = agent.tools.run

        def run(name, arguments):
            if name == "write_file":
                inbox.append("Сделай фон синим")
            return original(name, arguments)
        agent.tools.run = run
        self.assertEqual(agent.run(), "Готово")
        self.assertTrue(any(item["role"] == "user" and "Сделай фон синим" in item["content"] for item in seen[1]))

    def test_a_message_that_arrives_with_the_final_answer_is_not_lost(self):
        seen, inbox = [], []
        agent = self.agent([call("write_file", path="a.py", content="print(1)\n"), call("run_command", command="python a.py"), "Готово", "Теперь с цветом"], seen, incoming=lambda: [inbox.pop(0)] if inbox else [])
        original = agent.ask

        def ask(calls, info):
            answer = original(calls, info)
            if answer == "Готово":
                inbox.append("Добавь цвет")
            return answer
        agent.ask = ask
        self.assertEqual(agent.run(), "Теперь с цветом")
        self.assertIn("Добавь цвет", seen[-1][-1]["content"])

    def test_a_question_may_be_answered_without_tools(self):
        self.assertEqual(self.agent(["Этот код считает сумму."], request="Что делает этот код?", may_only_answer=True).run(), "Этот код считает сумму.")

    def test_unchecked_changes_get_one_reminder(self):
        seen = []
        agent = self.agent([call("write_file", path="a.py", content="print(1)\n"), "Готово", "Проверить нечем, сказал как есть"], seen)
        self.assertEqual(agent.run(), "Проверить нечем, сказал как есть")
        self.assertIn("after the last successful check", seen[2][-1]["content"])

    def test_unfinished_plan_gets_a_reminder(self):
        seen = []
        agent = self.agent([call("update_plan", items=[{"text": "шаг", "status": "pending"}]), call("write_file", path="a.py", content="print(1)\n"),
                            call("run_command", command="python a.py"), "Готово", "Всё"], seen)
        self.assertEqual(agent.run(), "Всё")
        self.assertIn("unfinished steps: шаг", seen[4][-1]["content"])

    def test_code_pasted_into_the_chat_is_sent_back(self):
        block = "```python\n" + "print(1)\n" * 10 + "```"
        seen = []
        agent = self.agent([call("read_file", path="missing"), block, "Текст"], seen)
        self.assertEqual(agent.run(), "Текст")
        self.assertIn("Do not put code", seen[2][-1]["content"])

    def test_text_form_calls_work_too(self):
        agent = self.agent(['{"name": "write_file", "arguments": {"path": "a.txt", "content": "x"}}', "Готово", "Всё"])
        agent.run()
        self.assertTrue((self.root / "a.txt").exists())

    def test_a_cut_off_write_is_saved_and_continued(self):
        seen = []
        agent = self.agent([call("write_file", _raw='{"path":"a.js","content":"//one\\n//two\\n//th'), call("write_file", path="a.js", content="//three\n", append=True), call("run_command", command="node a.js"), "Готово"], seen)
        self.assertEqual(agent.run(), "Готово")
        self.assertEqual((self.root / "a.js").read_text(encoding="utf-8"), "//one\n//two\n//three\n")
        self.assertIn("cut off", seen[1][-1]["content"])

    def test_reading_without_checking_gets_a_real_check(self):
        class Browser:
            def __init__(self):
                self.calls = 0

            def check_page(self, url, wait, script, screenshot, after_seconds=1, after_script="", explore=True):
                self.calls += 1
                return {"errors": ["Uncaught ReferenceError: x is not defined at game.js:3"], "page": {"title": "t"}}
        browser = Browser()
        tools = make_tools(self.root, ask=lambda *args: "once", browser=browser)
        seen = []
        steps = [call("write_file", path="index.html", content="<html></html>\n"), call("read_file", path="index.html"), call("outline", path="index.html"), call("run_command", command="findstr html index.html")]
        self.agent(steps, seen, tools=tools).run()
        self.assertEqual(browser.calls, 1)
        self.assertTrue(any("checked for you" in str(item.get("content")) and "x is not defined" in str(item.get("content")) for item in seen[4]))
        self.addCleanup(__import__("app.tools.preview", fromlist=["stop_all"]).stop_all)

    def test_a_look_at_files_is_not_a_check(self):
        tools = make_tools(self.root, ask=lambda *args: "once")
        tools.run("write_file", {"path": "a.py", "content": "print(1)\n"})
        tools.run("run_command", {"command": "findstr print a.py"})
        self.assertFalse(tools.verified)
        tools.run("run_command", {"command": "python a.py"})
        self.assertTrue(tools.verified)

    def test_searching_stops_after_a_few_tries_until_something_changes(self):
        (self.root / "a.py").write_text("print(1)\n", encoding="utf-8")
        tools = make_tools(self.root, ask=lambda *args: "once")
        for index in range(coding.LOOK_LIMIT):
            self.assertNotIn("Not run", tools.run("run_command", {"command": f"findstr /n print{index} a.py"}))
        self.assertIn("Not run", tools.run("run_command", {"command": "findstr /n /c:other a.py"}))
        self.assertEqual(tools.refused_looks, 1)
        self.assertNotIn("Not run", tools.run("run_command", {"command": "python a.py"}))
        tools.run("edit_file", {"path": "a.py", "old_text": "print(1)", "new_text": "print(2)"})
        self.assertNotIn("Not run", tools.run("run_command", {"command": "findstr /n print a.py"}))
        self.assertEqual(tools.refused_looks, 0)

    def test_an_agent_that_only_searches_is_told_to_finish(self):
        (self.root / "a.py").write_text("print(1)\n", encoding="utf-8")
        seen = []
        agent = self.agent([call("run_command", command=f"findstr /n word{index} a.py") for index in range(40)], seen, closing=["Не нашёл, что менять"])
        self.assertEqual(agent.run(), "Не нашёл, что менять")
        self.assertLess(len(seen), 13)

    def test_a_request_that_only_reads_gets_the_page_checked_once(self):
        class Browser:
            calls = 0

            def check_page(self, *arguments):
                Browser.calls += 1
                return {"errors": ["Uncaught TypeError: x at index.html:3"], "page": {"title": "t"}}
        (self.root / "index.html").write_text("<p>1</p>\n" * 20, encoding="utf-8")
        tools = make_tools(self.root, ask=lambda *args: "once", browser=Browser())
        seen = []
        agent = self.agent([call("read_file", path="index.html", offset=index) for index in range(1, 9)] + ["Готово"], seen, tools=tools, request="Почини меню")
        agent.run()
        self.assertEqual(Browser.calls, 1)
        self.assertTrue(any("Uncaught TypeError" in str(item.get("content")) and item["role"] == "user" for item in agent.context))

    def test_a_question_does_not_start_a_check(self):
        class Browser:
            calls = 0

            def check_page(self, *arguments):
                Browser.calls += 1
                return {"errors": [], "page": {}}
        (self.root / "index.html").write_text("<p>1</p>\n" * 20, encoding="utf-8")
        tools = make_tools(self.root, ask=lambda *args: "once", browser=Browser())
        agent = self.agent([call("read_file", path="index.html", offset=index) for index in range(1, 5)] + ["Это страница"], tools=tools, request="Что здесь?", may_only_answer=True)
        self.assertEqual(agent.run(), "Это страница")
        self.assertEqual(Browser.calls, 0)

    def test_endless_repeats_end_with_a_final_message(self):
        seen = []
        agent = self.agent([call("list_files")] * 20, seen)
        self.assertEqual(agent.run(), "All done.")
        self.assertLess(len(seen), 15)
        self.assertIn("no more tools", seen[-1][-1]["content"])

    PRINTED_EDIT = "<tool_call>\n<function=edit_file>\n<parameter=path>\na.txt\n</parameter>\n<parameter=old_text>\nold\n</parameter>\n<parameter=new_text>\nnew\n</parameter>\n</function>\n</tool_call>"

    def test_a_fix_printed_after_the_stop_is_made_and_the_work_goes_on(self):
        (self.root / "a.txt").write_text("old\n", encoding="utf-8")
        (self.root / "b.py").write_text("print(1)\n", encoding="utf-8")
        seen = []
        agent = self.agent([call("list_files")] * 12 + [call("run_command", command="python b.py"), "Готово"], seen, closing=[self.PRINTED_EDIT])
        self.assertEqual(agent.run(), "Готово")
        self.assertEqual((self.root / "a.txt").read_text(encoding="utf-8"), "new\n")
        self.assertFalse(agent.closing)

    def test_a_printed_call_is_never_the_final_message(self):
        printed = "<tool_call>\n<function=list_files>\n</function>\n</tool_call>"
        agent = self.agent([call("list_files")] * 12, closing=[printed, "Сделал половину"])
        self.assertEqual(agent.run(), "Сделал половину")
        agent = self.agent([call("list_files")] * 12, closing=[printed, printed, printed])
        self.assertIn("перестала отвечать", agent.run())

    def test_a_fix_that_keeps_failing_does_not_go_on_forever(self):
        seen = []
        agent = self.agent([call("list_files")] * 12, seen, closing=[self.PRINTED_EDIT] * 8)
        self.assertIn("перестала отвечать", agent.run())
        self.assertLess(len(seen), 20)

    def test_two_calls_taking_turns_are_noticed_too(self):
        seen = []
        agent = self.agent([call("list_files"), call("search", pattern="x")] * 20, seen)
        self.assertEqual(agent.run(), "All done.")
        self.assertLess(len(seen), 28)

    def test_many_steps_without_a_change_end_the_work(self):
        seen = []
        agent = self.agent([call("write_file", path="a.py", content="print(1)\n"), call("run_command", command="python a.py")] + [call("read_file", path="a.py", offset=index) for index in range(1, 60)], seen)
        self.assertEqual(agent.run(), "All done.")
        self.assertLess(len(seen), 30)

    def test_an_edit_starts_the_count_again(self):
        steps = []
        for index in range(30):
            steps += [call("write_file", path=f"f{index}.py", content="print(1)\n"), call("run_command", command=f"python f{index}.py")]
        seen = []
        self.agent(steps + ["Готово"], seen).run()
        self.assertEqual(len(seen), 61)

    def test_memory_shrinks_but_keeps_the_request_and_notes(self):
        big = "x = 1\n" * 3000
        steps = [call("write_file", path=f"f{index}.py", content=big) for index in range(6)] + [call("run_command", command="python f0.py"), "Готово"]
        seen = []
        agent = self.agent(steps, seen, size=8000)
        self.assertEqual(agent.run(), "Готово")
        self.assertTrue(any("Earlier step, already done" in json.dumps(context) for context in seen))
        self.assertLessEqual(max(sum(len(json.dumps(item)) // 3 for item in context) for context in seen[3:]), 8000 + 7000)
        first = next(item for item in seen[-1] if item["role"] == "user")
        self.assertIn("Сделай игру", first["content"])
        self.assertIn("Files changed so far", first["content"])
        self.assertEqual((self.root / "f0.py").read_text(encoding="utf-8"), big)

    def test_forgotten_files_leave_their_table_of_contents(self):
        code = "function spawnBurst() {}\nconst score = 0;\n" + "// filler\n" * 3000
        seen = []
        self.agent([call("write_file", path=f"f{index}.js", content=code) for index in range(5)] + [call("run_command", command="node --check f0.js"), "Готово"], seen, size=8000).run()
        self.assertTrue(any("defines: function spawnBurst; const score" in json.dumps(context, ensure_ascii=False) for context in seen))

    def test_forgotten_steps_leave_no_half_erased_call_to_imitate(self):
        big = "x = 1\n" * 3000
        steps = [call("write_file", path=f"f{index}.py", content=big) for index in range(4)] + [call("edit_file", path="f3.py", old_text="x = 1", new_text="x = 2"), "Готово"]
        seen = []
        self.agent(steps, seen, size=8000).run()
        last = json.dumps(seen[-1], ensure_ascii=False)
        self.assertNotIn("[removed to save memory", last)
        self.assertIn("Earlier step, already done", last)
        self.assertNotIn('"content": "x = 1', last.replace(big, ""))

    def test_a_placeholder_is_not_accepted_as_text_to_replace(self):
        (self.root / "a.py").write_text("x = 1\n", encoding="utf-8")
        tools = make_tools(self.root, ask=lambda *args: "once")
        result = tools.run("edit_file", {"path": "a.py", "old_text": "[removed to save memory, 4 lines]", "new_text": "[removed to save memory, 4 lines]"})
        self.assertIn("placeholder", result)
        self.assertEqual((self.root / "a.py").read_text(encoding="utf-8"), "x = 1\n")

    def test_memory_keeps_tool_results_next_to_their_calls(self):
        steps = [call("write_file", path=f"f{index}.py", content="x = 1\n" * 2000) for index in range(10)] + [call("run_command", command="python f0.py"), "Готово"]
        seen = []
        self.agent(steps, seen, size=7000).run()
        for context in seen:
            for place, item in enumerate(context):
                if item["role"] == "tool":
                    self.assertTrue(context[place - 1].get("tool_calls") or context[place - 1]["role"] == "tool")

    def test_context_error_shrinks_and_retries(self):
        replies = iter([RuntimeError("the request exceeds the available context size"), "Ответ"])

        def chat(context, specs, calls, info):
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return reply
        agent = agent_module.Agent(chat, make_tools(self.root), lambda text: 10, 16000, self.events.append, threading.Event(), "system", "Вопрос?", may_only_answer=True)
        self.assertEqual(agent.run(), "Ответ")

    def test_stop_button_ends_the_loop(self):
        cancel = threading.Event()
        cancel.set()
        agent = agent_module.Agent(scripted([]), make_tools(self.root), lambda text: 10, 16000, self.events.append, cancel, "system", "x")
        with self.assertRaises(InterruptedError):
            agent.run()

    def test_prompt_carries_the_project_notes_and_files(self):
        (self.root / "AGENTS.md").write_text("Use tabs.", encoding="utf-8")
        prompt = agent_module.build_system_prompt(self.root, 16000, True, True)
        self.assertIn("Use tabs.", prompt)
        self.assertIn("AGENTS.md", prompt)
        self.assertIn(str(self.root), prompt)
        self.assertIn("screenshot", prompt)
        self.assertNotIn("check_page", agent_module.build_system_prompt(self.root, 16000, False, False))


class Brake(unittest.TestCase):
    def test_long_thinking_restarts_the_step_without_thinking(self):
        brake = agent_module.ThinkingBrake(threading.Event(), 16000, "medium")
        asked = []

        def call(think, stop):
            asked.append(think)
            if think is False:
                return "ответ"
            brake.check("x" * 100000)
            self.assertTrue(stop.is_set())
            raise InterruptedError
        self.assertEqual(brake.run(call), "ответ")
        self.assertEqual(asked, ["medium", False])
        self.assertEqual(brake.run(call), "ответ")
        self.assertEqual(asked, ["medium", False, False])

    def test_the_stop_button_is_not_taken_for_the_brake(self):
        cancel = threading.Event()
        brake = agent_module.ThinkingBrake(cancel, 16000, "medium")

        def call(think, stop):
            cancel.set()
            raise InterruptedError
        with self.assertRaises(InterruptedError):
            brake.run(call)


class RealModelPath(unittest.TestCase):
    def test_streaming_reports_the_end_reason_and_tool_progress(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from unittest import mock
        from types import SimpleNamespace
        from app.models import llama

        class Handler(BaseHTTPRequestHandler):
            sent = {}

            def do_POST(self):
                Handler.sent = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(200)
                self.end_headers()
                chunks = [{"choices": [], "prompt_progress": {"total": 10, "processed": 5}},
                          {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "write_file", "arguments": '{"path":"a.js",'}}]}}]},
                          {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"content":"x"}'}}]}, "finish_reason": "tool_calls"}]}]
                for chunk in chunks:
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")

            def log_message(self, *args):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        target = SimpleNamespace(base_url=f"http://127.0.0.1:{server.server_address[1]}", in_use=0, last_used=0)
        calls, info, seen, statuses = [], {}, [], []
        with mock.patch.object(llama, "prepare", return_value=target), mock.patch.object(llama, "_record_speed"):
            llama.chat("model", [{"role": "user", "content": "hi"}], think=False, on_status=statuses.append, overrides={"return_progress": True},
                       tools=[{"type": "function"}], tool_calls=calls, on_tool_text=lambda slots: seen.append(slots[0]["name"]), info=info)
        self.assertEqual(calls[0]["arguments"], {"path": "a.js", "content": "x"})
        self.assertEqual(info["finish"], "tool_calls")
        self.assertEqual(seen[0], "write_file")
        self.assertIn("Читает контекст · 50%", statuses)
        self.assertTrue(Handler.sent["return_progress"])


class Routing(unittest.TestCase):
    def test_programs_go_to_the_agent(self):
        for text in ("Напиши игру змейка", "сделай мне простую игру про кота", "Создай сайт-визитку", "Сделай простой калькулятор на HTML", "Напиши телеграм бота", "write a snake game", "Make a simple calculator in HTML"):
            self.assertTrue(commands.asks_new_project(text), text)
            self.assertEqual(core.CompanionCore._detect_composer_route(text), "code", text)

    def test_programs_named_in_other_words_go_to_the_agent(self):
        for text in ("Напиши клон майнкрафта", "сделай змейку", "Создай тетрис", "Напиши симулятор фермы", "Напиши пример на питоне", "сделай шутер на pygame", "Make a Minecraft clone", "write a tetris in python"):
            self.assertEqual(core.CompanionCore._detect_composer_route(text), "code", text)

    def test_a_named_code_file_goes_to_the_agent(self):
        for text in ("Я написал клон Minecraft и сохранил на Рабочем столе как minicraft.py. Как тебе запустить? — Улучшить", "что делает game.js", "открой index.html и поправь", "улучши код", "доработай программу"):
            self.assertEqual(core.CompanionCore._detect_composer_route(text), "code", text)
        self.assertEqual(commands.code_file_names("посмотри minicraft.py и game.JS"), ["minicraft.py", "game.JS"])

    def test_words_that_only_look_like_it_stay_in_the_chat(self):
        for text in ("Что такое node.js?", "Напиши рассказ про змейку", "Напиши стих о майнкрафте", "Как дела? Сделай паузу.", "Улучши этот текст", "Напиши письмо на python конференцию про игры", "Расскажи про шахматы", "сделай чай.exe"):
            self.assertEqual(core.CompanionCore._detect_composer_route(text), "chat", text)

    def test_talk_about_programs_stays_in_the_chat(self):
        for text in ("Напиши отзыв про игру Ведьмак", "Посоветуй игру на вечер", "Напиши письмо другу", "Как дела?", "Что такое игра Го?", "Write a review about this game"):
            self.assertFalse(commands.asks_new_project(text), text)
            self.assertEqual(core.CompanionCore._detect_composer_route(text), "chat", text)

    def test_project_names_are_safe_for_a_folder(self):
        self.assertEqual(commands.project_name("Напиши игру змейка для браузера"), "zmeyka")
        self.assertEqual(commands.project_name("write a snake game"), "snake")
        self.assertEqual(commands.project_name("???"), "")

    def test_only_a_question(self):
        self.assertTrue(commands.asks_only_question("Что делает этот код?"))
        self.assertTrue(commands.asks_only_question("объясни этот файл"))
        self.assertFalse(commands.asks_only_question("Напиши игру змейка"))
        self.assertFalse(commands.asks_only_question("Исправь ошибку в проекте"))


class ProjectsAndChats(unittest.TestCase):
    def state(self, chats, active):
        import functools
        import types
        made = []
        state = types.SimpleNamespace(chats=chats, active_chat_id=active, memory=types.SimpleNamespace(forget_chat=lambda chat_id: None), _save_conversation=lambda: None)
        state._active_chat = lambda: next((chat for chat in state.chats if chat["id"] == state.active_chat_id), None)
        state.select_chat = lambda chat_id: (setattr(state, "active_chat_id", chat_id), chat_id)[1]
        state.create_chat = lambda code=False: (made.append(code), state.select_chat("fresh-code" if code else "fresh"))[1]
        state.open_chat_of_kind = functools.partial(core.CompanionCore.open_chat_of_kind, state)
        state.made = made
        return state

    def test_the_switch_opens_the_latest_of_its_kind_or_starts_one(self):
        chats = [{"id": "a", "updated": 5}, {"id": "p1", "code_on": True, "updated": 3}, {"id": "p2", "code_on": True, "updated": 9}, {"id": "b", "updated": 7}]
        state = self.state(chats, "a")
        self.assertEqual(core.CompanionCore.open_chat_of_kind(state, True), "p2")
        self.assertEqual(core.CompanionCore.open_chat_of_kind(state, False), "b")
        only_chats = self.state([{"id": "a"}], "a")
        self.assertEqual(core.CompanionCore.open_chat_of_kind(only_chats, True), "fresh-code")
        self.assertEqual(only_chats.made, [True])

    def test_deleting_a_project_stays_among_projects(self):
        state = self.state([{"id": "a", "updated": 9}, {"id": "p1", "code_on": True}, {"id": "p2", "code_on": True, "updated": 2}], "p1")
        self.assertEqual(core.CompanionCore.delete_chat(state, "p1"), "p2")
        state = self.state([{"id": "a"}, {"id": "p1", "code_on": True}], "p1")
        self.assertEqual(core.CompanionCore.delete_chat(state, "p1"), "fresh-code")
        state = self.state([{"id": "a"}, {"id": "b"}, {"id": "p1", "code_on": True}], "a")
        self.assertEqual(core.CompanionCore.delete_chat(state, "a"), "b")


def types_like(app):
    import types
    return types.SimpleNamespace(_app=app)


class CodeOffer(unittest.TestCase):
    def box(self, offered=None):
        from app.tools import toolbox
        with tempfile.TemporaryDirectory() as folder:
            return toolbox.ToolBox(Path(folder), Path(folder), use_mcp=False, on_code_offer=offered)

    def names(self, box):
        return [spec["function"]["name"] for spec in box.specs()]

    def test_the_model_can_offer_and_that_ends_its_turn(self):
        calls = []
        box = self.box(lambda: calls.append(1))
        self.assertIn("offer_code_mode", self.names(box))
        self.assertIn("offer_code_mode", box.skills_prompt())
        box.run("offer_code_mode", {})
        self.assertEqual(calls, [1])
        self.assertTrue(box.turn_over)
        self.assertTrue(box.poll_note)

    def test_no_offer_after_the_user_declined(self):
        box = self.box()
        self.assertNotIn("offer_code_mode", self.names(box))
        self.assertNotIn("offer_code_mode", box.skills_prompt())
        self.assertIn("Нет такого инструмента", box.run("offer_code_mode", {}))

    def test_the_card_remembers_the_request(self):
        card = json.loads(core.CompanionCore.code_offer_card("Напиши змейку"))
        self.assertEqual(card, {"kind": "offer", "request": "Напиши змейку"})


class CodeOfferAnswers(unittest.TestCase):
    def setUp(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("main_window", str(Path(__file__).resolve().parents[1] / "app" / "window" / "main.pyw"))
        spec = importlib.util.spec_from_loader("main_window", loader)
        self.web = importlib.util.module_from_spec(spec)
        loader.exec_module(self.web)

    def app(self, chat, **fields):
        import types
        self.started = []
        self.finished = threading.Event()
        def start(name):
            def run(*args):
                self.started.append((name, args[0]))
                self.finished.set()
            return run
        base = dict(_state_lock=threading.RLock(), dialogue_items=[{"role": "code", "text": core.CompanionCore.code_offer_card("Напиши змейку")}], settings={"model": "m"}, busy=False,
                    action_cancel=threading.Event(), speech_enabled=False, selected_model="", _active_response=None, _activity="", _save_conversation=lambda: None, _changed=lambda: None,
                    _active_chat=lambda: chat, _run_coding_agent=start("agent"), ask_model=start("chat"))
        base.update(fields)
        return types.SimpleNamespace(**base)

    def answer(self, app, accept):
        return self.web.WebApi.answer_code_offer(types_like(app), 0, accept)

    def test_accepting_turns_the_chat_into_a_project_and_starts_the_agent(self):
        chat = {}
        app = self.app(chat)
        self.assertTrue(self.answer(app, True)["ok"])
        self.assertTrue(self.finished.wait(2))
        self.assertTrue(chat["code_on"])
        self.assertEqual(self.started, [("agent", "Напиши змейку")])
        self.assertEqual(json.loads(app.dialogue_items[0]["text"])["answered"], "code")
        self.assertFalse(self.answer(app, True)["ok"])

    def test_declining_answers_in_the_chat_and_stops_offering(self):
        chat = {}
        app = self.app(chat)
        self.assertTrue(self.answer(app, False)["ok"])
        self.assertTrue(self.finished.wait(2))
        self.assertTrue(chat["code_declined"])
        self.assertNotIn("code_on", chat)
        self.assertEqual(self.started, [("chat", "Напиши змейку")])
        state = self.app(chat, running=False, _detect_composer_route=core.CompanionCore._detect_composer_route, _continues_code=lambda chat, text: False)
        self.assertEqual(self.web.WebCompanion._route_for(state, "Напиши змейку"), "chat")
        self.assertEqual(self.web.WebCompanion._route_for(self.app({}, running=False, _detect_composer_route=core.CompanionCore._detect_composer_route, _continues_code=lambda chat, text: False), "Напиши змейку"), "code")

    def test_nothing_starts_while_another_answer_runs(self):
        chat = {}
        app = self.app(chat, busy=True)
        self.assertFalse(self.answer(app, True)["ok"])
        self.assertEqual(chat, {})
        self.assertEqual(self.started, [])


EDGE = next((path for path in (Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"), Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")) if path.is_file()), None)
MOUSE_PAGE = """<!doctype html><html><body style="margin:0"><script>%s</script>
<canvas id="c" width="400" height="300" style="display:block"></canvas><button id="go" style="position:fixed;left:500px;top:10px;width:60px;height:30px">Go</button><pre id="out"></pre>
<script>
var seen=[],out={};
['mousedown','mouseup','click','contextmenu','mousemove','pointerdown'].forEach(function(t){document.addEventListener(t,function(e){seen.push(t+':'+e.target.id+':'+e.button+':'+Math.round(e.clientX)+','+Math.round(e.clientY)+':'+e.movementX);});});
var look=[];document.getElementById('go').onclick=function(){out.button=true;};
document.addEventListener('pointerlockchange',function(){look.push(document.pointerLockElement?document.pointerLockElement.id:'none');});
out.left=clickAt(100,50);out.leftSeen=seen.slice();seen.length=0;
out.right=clickAt(0.25,0.1,'right');out.rightHas=seen.some(function(s){return s.indexOf('contextmenu:c:2')===0;});seen.length=0;
out.selector=click('#go');out.missing=click('#nothing');seen.length=0;
out.drag=drag(10,10,110,60);out.dragSeen=seen.slice();seen.length=0;
document.getElementById('c').requestPointerLock();out.lock=look.slice();
out.move=moveMouse(25,-5);out.moveSeen=seen.slice();out.at=clickAt(450,250);
document.exitPointerLock();out.unlocked=look.slice();
document.getElementById('out').textContent='RESULT'+JSON.stringify(out)+'END';
</script></body></html>"""


@unittest.skipUnless(EDGE, "needs Microsoft Edge")
class AgentMouse(unittest.TestCase):
    def test_the_agent_can_use_the_mouse_on_a_page(self):
        import ast
        import re
        import subprocess
        source = (Path(__file__).resolve().parents[1] / "app" / "window" / "browser.py").read_text(encoding="utf-8")
        PAGE_ERRORS = next(ast.literal_eval(node.value) for node in ast.parse(source).body if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "PAGE_ERRORS")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            page = Path(folder) / "page.html"
            page.write_text(MOUSE_PAGE % PAGE_ERRORS, encoding="utf-8")
            dom = subprocess.run([str(EDGE), "--headless", "--disable-gpu", "--no-first-run", f"--user-data-dir={folder}\\profile", "--window-size=800,600", "--virtual-time-budget=500", "--dump-dom", page.as_uri()],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout
        out = json.loads(re.search(r'<pre id="out">RESULT(.*?)END</pre>', dom, re.S).group(1))
        self.assertEqual(out["left"], "clicked canvas#c at 100,50")
        self.assertEqual([row.split(":")[0] for row in out["leftSeen"]], ["mousemove", "pointerdown", "mousedown", "mouseup", "click"])
        self.assertTrue(all(":c:0:100,50:" in row for row in out["leftSeen"]))
        self.assertIn("canvas#c", out["right"])
        self.assertTrue(out["rightHas"])
        self.assertEqual(out["selector"], "clicked button#go")
        self.assertTrue(out["button"])
        self.assertEqual(out["missing"], "nothing matches #nothing")
        self.assertEqual(out["dragSeen"][1].split(":")[0], "pointerdown")
        self.assertEqual(out["dragSeen"][-1].split(":")[0], "mouseup")
        self.assertIn("mousemove:c:0:110,60:20", out["dragSeen"])
        self.assertEqual(out["lock"], ["c"])
        self.assertEqual(out["moveSeen"][-1].split(":")[-1], "25")
        self.assertIn("canvas#c", out["at"])
        self.assertEqual(out["unlocked"], ["c", "none"])


CLICK_PAGE = """<!doctype html><html><body style="margin:0"><script>@ERRORS@</script>
<button id="ok" onclick="this.textContent='opened'">Open</button>
<button id="dead">Dead</button>
<button id="boom" onclick="nothing.here()">Boom</button>
<button id="hidden">Hidden under</button>
<button id="fake" onclick="document.getElementById('menu').classList.toggle('hidden')">Only a class</button>
<div style="position:fixed;left:0;top:0;width:100%;height:100%;pointer-events:auto;background:rgba(0,0,0,0.01);z-index:5" id="veil"></div>
<div id="menu"><button id="start" style="position:fixed;left:40%;top:40%;z-index:9" onclick="document.getElementById('veil').remove();this.remove()">Play</button></div>
<pre id="out"></pre>
<script>
var NEXT=@NEXT@, SIG=@SIG@, PRESS=@PRESS@, rows=[], n=0;
function errs(){return window.__pivenErrors.slice();}
function step(){
  var item=JSON.parse(eval(NEXT)||'null');
  if(!item||n++>12){document.getElementById('out').textContent='RESULT'+JSON.stringify(rows)+'END';return;}
  var before=eval(SIG),known=errs().length,info=JSON.parse(eval(PRESS));
  setTimeout(function(){rows.push({name:item.name,label:item.label,changed:before!==eval(SIG),covered:info.covered,fresh:errs().slice(known)});step();},30);
}
setTimeout(step,50);
</script></body></html>"""


class ClickThrough(unittest.TestCase):
    def test_every_control_is_pressed_and_the_dead_ones_are_found(self):
        import ast
        import re
        import subprocess
        source = (Path(__file__).resolve().parents[1] / "app" / "window" / "browser.py").read_text(encoding="utf-8")
        values = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(source).body if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in ("PAGE_ERRORS", "PAGE_NEXT_CLICK", "PAGE_SIGNATURE", "PAGE_CLICK")}
        html = CLICK_PAGE.replace("@ERRORS@", values["PAGE_ERRORS"]).replace("@NEXT@", json.dumps(values["PAGE_NEXT_CLICK"])).replace("@SIG@", json.dumps(values["PAGE_SIGNATURE"])).replace("@PRESS@", json.dumps(values["PAGE_CLICK"]))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            page = Path(folder) / "page.html"
            page.write_text(html, encoding="utf-8")
            dom = subprocess.run([str(EDGE), "--headless", "--disable-gpu", "--no-first-run", f"--user-data-dir={folder}\profile", "--window-size=800,600", "--virtual-time-budget=6000", "--dump-dom", page.as_uri()],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90).stdout
        rows = {row["name"]: row for row in json.loads(re.search(r'<pre id="out">RESULT(.*?)END</pre>', dom, re.S).group(1))}
        self.assertEqual(set(rows), {"button#ok", "button#dead", "button#boom", "button#hidden", "button#fake", "button#start"})
        self.assertFalse(rows["button#fake"]["changed"])
        self.assertTrue(rows["button#start"]["changed"])
        self.assertEqual([row["name"] for row in list(rows.values())[:1]], ["button#start"])
        self.assertTrue(rows["button#ok"]["changed"])
        self.assertFalse(rows["button#dead"]["changed"])
        self.assertEqual(rows["button#dead"]["covered"], "")
        self.assertTrue(any("nothing" in error for error in rows["button#boom"]["fresh"]))


class WindowChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "project"
        self.root.mkdir()

    def test_steps_are_read_from_plain_words(self):
        from unittest import mock
        from app.tools import desktop
        with mock.patch.object(desktop, "click") as click, mock.patch.object(desktop, "drag") as drag, mock.patch.object(desktop, "key") as key:
            self.assertIn("done", desktop.run_step(7, "click 0.5 0.5"))
            click.assert_called_with(7, 0.5, 0.5, "left")
            desktop.run_step(7, "click 10 20 RIGHT")
            click.assert_called_with(7, 10.0, 20.0, "right")
            desktop.run_step(7, "drag 1 2 3 4")
            drag.assert_called_with(7, 1.0, 2.0, 3.0, 4.0, "left")
            desktop.run_step(7, "key w 0.5")
            key.assert_called_with(7, "w", 0.5)
            desktop.run_step(7, "key space")
            key.assert_called_with(7, "space", 0.1)
        for step in ("fly away", "click", "click a b", "key"):
            self.assertNotIn(": done", desktop.run_step(7, step), step)

    def test_unknown_keys_and_buttons_are_refused(self):
        from app.tools import desktop
        self.assertIn("not understood", desktop.run_step(0, "key nothing-like-it"))
        self.assertIn("not understood", desktop.run_step(0, "click 1 1 thumb"))

    def test_a_program_needs_permission_like_any_command(self):
        started = []
        tools = make_tools(self.root, ask=lambda command, reason, can_trust: False)
        tools._start = lambda command, shell: started.append(command)
        self.assertIn("did not allow", tools.run("check_window", {"command": "python game.py"}))
        self.assertEqual(started, [])
        self.assertIn("not allowed", make_tools(self.root, mode="free").run("check_window", {"command": "shutdown /s"}))

    def test_a_program_without_a_window_is_not_a_success(self):
        (self.root / "a.py").write_text("print('только текст')\n", encoding="utf-8")
        tools = make_tools(self.root, mode="free")
        tools.verified = False
        reply = tools.run("check_window", {"command": "python a.py"})
        self.assertIn("never opened a window", reply)
        self.assertIn("только текст", reply)
        self.assertFalse(tools.verified)

    def test_a_good_run_reports_steps_and_keeps_the_picture(self):
        from unittest import mock
        from app.tools import desktop
        (self.root / "a.py").write_text("import time\nprint('started', flush=True)\ntime.sleep(30)\n", encoding="utf-8")
        tools = make_tools(self.root, mode="free", vision=True)
        tools.verified = False
        with mock.patch.object(desktop, "find_window", return_value=7), mock.patch.object(desktop, "run_step", side_effect=lambda window, step, cancelled: f"{step}: done"), \
                mock.patch.object(desktop, "picture", return_value=("shot", False)), mock.patch.object(desktop, "client_size", return_value=(640, 400)), mock.patch.object(desktop, "title", return_value="Игра"):
            reply = tools.run("check_window", {"command": "python a.py", "steps": ["click 1 2"], "wait_seconds": 0.5, "screenshot": True})
        self.assertIn("still running", reply)
        self.assertIn("«Игра», 640x400", reply)
        self.assertIn("click 1 2: done", reply)
        self.assertTrue(tools.verified)
        self.assertEqual((tools.picture, tools.pending_image, tools.window_command), ("shot", "shot", "python a.py"))

    def test_the_final_picture_reruns_a_changed_program(self):
        import types
        tools = make_tools(self.root, mode="free")
        ran = []
        tools.run = lambda name, arguments: (ran.append((name, arguments["command"])), setattr(tools, "picture", "new"), setattr(tools, "picture_edits", tools.edits))
        tools.window_command, tools.picture, tools.picture_edits, tools.edits = "python a.py", "old", 0, 1
        agent = types.SimpleNamespace(tools=tools, put=lambda event: None, _start_page=lambda: None)
        self.assertEqual(agent_module.Agent.result_picture(agent), "new")
        self.assertEqual(ran, [("check_window", "python a.py")])


class ResultPicture(unittest.TestCase):
    def agent(self, root, browser):
        import types
        tools = make_tools(root, browser=browser)
        put = []
        return types.SimpleNamespace(tools=tools, put=put.append, _start_page=lambda: agent_module.Agent._start_page(types.SimpleNamespace(tools=tools))), tools

    def test_the_picture_shows_the_files_as_they_are_now(self):
        class Browser:
            calls = 0

            def check_page(self, *arguments):
                Browser.calls += 1
                return {"errors": [], "page": {"title": "t"}, "picture": f"shot{Browser.calls}"}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "project"
            root.mkdir()
            agent, tools = self.agent(root, Browser())
            tools.run("write_file", {"path": "index.html", "content": "<p>1</p>"})
            self.assertEqual(agent_module.Agent.result_picture(agent), "shot1")
            self.assertEqual(agent_module.Agent.result_picture(agent), "shot1")
            self.assertEqual(Browser.calls, 1)
            tools.run("write_file", {"path": "index.html", "content": "<p>2</p>"})
            self.assertEqual(agent_module.Agent.result_picture(agent), "shot2")

    def test_no_page_no_picture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "project"
            root.mkdir()
            agent, tools = self.agent(root, None)
            tools.run("write_file", {"path": "game.py", "content": "print(1)\n"})
            self.assertIsNone(agent_module.Agent.result_picture(agent))


class SpentTools(unittest.TestCase):
    def test_a_printed_call_is_not_an_answer(self):
        from app.tools import toolbox
        call = "<tool_call>\n<function=run_code>\n<parameter=code>\n$s = 1\n</parameter>\n</function>\n</tool_call>"
        self.assertEqual(toolbox.without_calls(call), "")
        self.assertEqual(toolbox.without_calls("Успел две части.\n" + call), "Успел две части.")
        self.assertEqual(toolbox.without_calls("Осталось так.\n<tool_call>\n<function=run_code>\n$s = 1"), "Осталось так.")
        self.assertEqual(toolbox.without_calls("<function=run_code>$s = 1</function>"), "")
        self.assertEqual(toolbox.without_calls("Обычный ответ"), "Обычный ответ")


class ComputerSkill(unittest.TestCase):
    def test_it_can_read_code_files(self):
        from app.tools import computer
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "minicraft.py"
            path.write_text("print('блок')", encoding="utf-8")
            self.assertIn("print('блок')", computer.execute_computer_action({"computer_action": "read_file", "path": str(path)}))


class DataFolderMove(unittest.TestCase):
    def setUp(self):
        from app import paths
        self.paths = paths
        self.addCleanup(setattr, paths, "DATA_DIR", paths.DATA_DIR)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.local = Path(temp.name)
        self.old = self.local / "OllamaCompanion"
        self.new = self.local / "PIVEN"

    def fill_old(self):
        self.old.mkdir()
        (self.old / "conversation.json").write_text(json.dumps({"image": "C:\\Users\\me\\AppData\\Local\\OllamaCompanion\\code_shots\\a.jpg", "text": "OllamaCompanion alone stays"}), encoding="utf-8")

    def test_the_old_folder_is_renamed_and_saved_paths_follow(self):
        self.fill_old()
        self.assertEqual(self.paths.migrate(self.local), self.new)
        self.assertFalse(self.old.exists())
        saved = json.loads((self.new / "conversation.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["image"], "C:\\Users\\me\\AppData\\Local\\PIVEN\\code_shots\\a.jpg")
        self.assertEqual(saved["text"], "OllamaCompanion alone stays")
        self.assertEqual(list(self.new.glob("*.moving")), [])

    def test_a_busy_folder_stays_in_use(self):
        from unittest import mock
        self.fill_old()
        with mock.patch.object(Path, "rename", side_effect=PermissionError("busy")):
            self.assertEqual(self.paths.migrate(self.local), self.old)
        self.assertEqual(self.paths.DATA_DIR, self.old)
        self.assertTrue((self.old / "conversation.json").exists())

    def test_a_folder_already_moved_is_left_alone(self):
        self.fill_old()
        self.new.mkdir()
        (self.new / "settings.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.paths.migrate(self.local), self.new)
        self.assertTrue(self.old.exists())

    def test_looking_up_the_folder_moves_nothing(self):
        self.fill_old()
        self.assertEqual(self.paths.current(self.local), self.old)
        self.assertTrue(self.old.exists())
        self.assertFalse(self.new.exists())

    def test_a_new_install_starts_in_the_new_folder(self):
        self.assertEqual(self.paths.current(self.local), self.new)
        self.assertEqual(self.paths.migrate(self.local), self.new)


class ProjectFolders(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.core = core.CompanionCore.__new__(core.CompanionCore)
        self.core.settings = {"project_root": str(self.base)}

    def test_a_new_program_gets_its_own_folder_and_the_chat_keeps_it(self):
        first = self.core._code_root({}, "Напиши игру змейка")
        self.assertEqual(first, self.base / "zmeyka")
        self.assertTrue(first.is_dir())
        self.assertEqual(self.core._code_root({}, "Напиши игру змейка"), self.base / "zmeyka-2")
        self.assertEqual(self.core._code_root({"code_root": str(first)}, "Напиши игру змейка"), first)

    def test_a_chat_without_a_folder_never_lands_in_another_project(self):
        (self.base / "companion-mod").mkdir()
        (self.base / "companion-mod" / "build.gradle").write_text("", encoding="utf-8")
        root = self.core._code_root({}, "Исправь ошибку в проекте")
        self.assertEqual(root.parent, self.base)
        self.assertNotEqual(root.name, "companion-mod")
        self.assertEqual(list(root.iterdir()), [])

    def test_a_named_file_is_found_where_it_lies(self):
        from unittest import mock
        home = self.base / "home"
        (home / "Desktop").mkdir(parents=True)
        (home / "Desktop" / "minicraft.py").write_text("", encoding="utf-8")
        (self.base / "old-game").mkdir()
        (self.base / "old-game" / "tetris.py").write_text("", encoding="utf-8")
        with mock.patch.object(Path, "home", return_value=home):
            self.assertEqual(self.core._code_root({}, "улучши minicraft.py"), home / "Desktop")
            self.assertEqual(self.core._code_root({}, "улучши tetris.py"), self.base / "old-game")
            self.assertEqual(self.core._code_root({}, "напиши новый файл nothing.py").parent, self.base)

    def test_a_common_file_name_does_not_pull_the_chat_into_a_project(self):
        from unittest import mock
        home = self.base / "home"
        home.mkdir()
        (self.base / "site").mkdir()
        (self.base / "main.py").write_text("", encoding="utf-8")
        (self.base / "site" / "index.html").write_text("", encoding="utf-8")
        with mock.patch.object(Path, "home", return_value=home):
            for text in ("исправь main.py", "поправь index.html"):
                root = self.core._code_root({}, text)
                self.assertEqual(root.parent, self.base, text)
                self.assertEqual(list(root.iterdir()), [], text)

    def test_a_name_found_in_two_projects_picks_neither(self):
        from unittest import mock
        home = self.base / "home"
        home.mkdir()
        for folder in ("one", "two"):
            (self.base / folder).mkdir()
            (self.base / folder / "tetris.py").write_text("", encoding="utf-8")
        with mock.patch.object(Path, "home", return_value=home):
            root = self.core._code_root({}, "улучши tetris.py")
        self.assertNotIn(root.name, ("one", "two"))
        self.assertEqual(list(root.iterdir()), [])

    def test_a_follow_up_finds_the_file_from_the_chat(self):
        from unittest import mock
        home = self.base / "home"
        (home / "Desktop").mkdir(parents=True)
        (home / "Desktop" / "minicraft.py").write_text("", encoding="utf-8")
        chat = {"items": [{"role": "user", "text": "Напиши игру"}, {"role": "system", "text": "Файл «minicraft.py» создан."}, {"role": "assistant", "text": "Готово."}]}
        self.assertTrue(self.core._continues_code(chat, "Добавь инвентарь"))
        self.assertTrue(self.core._continues_code(chat, "Я сохранил файл. Как тебе запустить? — Улучшить"))
        self.assertFalse(self.core._continues_code(chat, "Как дела?"))
        self.assertFalse(self.core._continues_code({"items": [{"role": "user", "text": "Привет"}]}, "Добавь инвентарь"))
        with mock.patch.object(Path, "home", return_value=home):
            self.assertEqual(self.core._code_root(chat, "Добавь инвентарь"), home / "Desktop")

    def test_short_replies_about_a_written_program_go_to_the_agent(self):
        chat = {"items": [{"role": "assistant", "text": "Сохранил minicraft.py на Рабочем столе."}]}
        for text in ("создай", "еще раз попробуй", "ещё раз", "так ты можешь файл открыть", "давай", "Да!", "продолжай",
                     "не запускается", "делай", "можешь pygame скачать", "При запуске сразу закрывается, я предлагаю на Ursina перейти", "сюда то зачем отправлять"):
            self.assertTrue(self.core._continues_code(chat, text), text)
        for text in ("Как дела?", "спасибо", "Привет!", "пока"):
            self.assertFalse(self.core._continues_code(chat, text), text)

    def test_tool_lines_do_not_push_the_file_out_of_the_chat_memory(self):
        items = [{"role": "assistant", "text": "Сохранил minicraft.py."}] + [{"role": "system", "text": "Инструмент · Запускает код (powershell)"}] * 30
        self.assertEqual(self.core._recent_code_files({"items": items}), ["minicraft.py"])

    def test_a_path_in_the_request_wins(self):
        other = self.base / "other"
        other.mkdir()
        (other / "a.py").write_text("", encoding="utf-8")
        self.assertEqual(self.core._code_root({}, f"Исправь {other}\\a.py пожалуйста"), other)
        self.assertEqual(self.core._code_root({}, f"Посмотри папку {other}"), other)


class ApiCheck(unittest.TestCase):
    """Checks a written file against the installed libraries."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "project"
        self.root.mkdir()
        self.tools = make_tools(self.root, ask=lambda *args: "once")
        if not self.tools._python():
            self.skipTest("no python on PATH")

    def test_names_a_library_does_not_have_are_reported_together(self):
        result = self.tools.run("write_file", {"path": "a.py", "content": "import random\nfrom os import path, nosuchthing\nprint(random.randint(1, 2), random.randint2(1, 2), undefined_name)\n"})
        self.assertIn("random has no attribute randint2", result)
        self.assertIn("cannot import nosuchthing from os", result)
        self.assertIn("name undefined_name is not defined", result)

    def test_a_correct_file_gets_no_report(self):
        result = self.tools.run("write_file", {"path": "a.py", "content": "import random, math\nfrom os import path\nclass A:\n    def f(self, n):\n        return [math.sqrt(n) for n in range(n)] + [random.random(), path.sep]\n"})
        self.assertNotIn("API check", result)

    def test_project_files_and_own_names_are_not_judged(self):
        (self.root / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
        result = self.tools.run("write_file", {"path": "a.py", "content": "import helper\nfrom helper import *\nrandom = helper\nprint(helper.VALUE, random.anything, VALUE)\n"})
        self.assertNotIn("API check", result)

    def test_a_missing_package_is_named(self):
        result = self.tools.run("write_file", {"path": "a.py", "content": "import nosuchpackage_zz\nnosuchpackage_zz.run()\n"})
        self.assertIn("nosuchpackage_zz is not installed", result)

    def test_edits_are_checked_too(self):
        self.tools.run("write_file", {"path": "a.py", "content": "import random\nprint(random.random())\n"})
        result = self.tools.run("edit_file", {"path": "a.py", "old_text": "random.random()", "new_text": "random.randomm()"})
        self.assertIn("random has no attribute randomm", result)

    def test_inspect_api_shows_the_real_names(self):
        result = self.tools.run("inspect_api", {"name": "random", "match": "randi"})
        self.assertIn("randint", result)
        self.assertIn("has no attribute", self.tools.run("inspect_api", {"name": "random.nothing"}))
        self.assertIn("not installed", self.tools.run("inspect_api", {"name": "nosuchpackage_zz"}))
        self.assertTrue(self.tools.run("inspect_api", {"name": "os; rm"}).startswith("Error"))
        self.assertIn("inspect_api", [spec["function"]["name"] for spec in self.tools.specs()])


if __name__ == "__main__":
    unittest.main()

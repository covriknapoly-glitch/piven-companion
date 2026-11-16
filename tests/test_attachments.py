import importlib.machinery
import importlib.util
import sys
import tempfile
import threading
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.chat import attachments


class ReadingFiles(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def file(self, name, data):
        path = self.folder / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    def test_text_and_code_are_read_in_utf8_or_windows_cyrillic(self):
        self.assertEqual(attachments.read_text(self.file("a.md", "﻿Привет\r\nмир")), "Привет\nмир")
        self.assertEqual(attachments.read_text(self.file("b.txt", "Старый файл".encode("cp1251"))), "Старый файл")
        self.assertEqual(attachments.read_text(self.file("Makefile", "all:\n\techo hi")), "all:\n\techo hi")

    def test_binary_files_are_refused_with_a_reason(self):
        self.assertIn("не текстовый", attachments.check(self.file("x.dat", b"MZ\x00\x01\x02")))
        self.assertIn("не умею", attachments.check(self.file("x.zip", b"PK plain looking")))
        self.assertIn("нет текста", attachments.check(self.file("empty.txt", "   ")))

    def test_word_document_keeps_paragraphs_tabs_and_entities(self):
        path = self.folder / "doc.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml",
                             '<w:document><w:body><w:p><w:r><w:t>Один</w:t></w:r><w:r><w:tab/><w:t xml:space="preserve">два &amp; три</w:t></w:r></w:p>'
                             '<w:p><w:r><w:t>Второй</w:t><w:br/><w:t>абзац</w:t></w:r></w:p></w:body></w:document>')
        self.assertEqual(attachments.read_text(path), "Один\tдва & три\nВторой\nабзац")

    def test_pdf_without_its_module_says_so(self):
        path = self.file("a.pdf", b"%PDF-1.4")
        with mock.patch.dict(sys.modules, {"pypdf": None}):
            self.assertIn("pypdf", attachments.check(path))

    def test_files_share_the_budget_short_ones_whole(self):
        short, long_one = self.file("short.txt", "s" * 100), self.file("long.txt", "l" * 5000)
        block = attachments.prompt_block([short, long_one], 1100)
        self.assertIn('<file name="short.txt">\n' + "s" * 100 + "\n</file>", block)
        self.assertIn("l" * 1000 + "\n[файл обрезан: здесь первые 1000 из 5000 символов]", block)
        self.assertNotIn("l" * 1001, block)

    def test_a_file_that_disappeared_is_named_not_dropped(self):
        block = attachments.prompt_block([self.folder / "gone.txt"], 1000)
        self.assertIn('<file name="gone.txt">\n[не удалось прочитать', block)


class SendingFiles(unittest.TestCase):
    def setUp(self):
        loader = importlib.machinery.SourceFileLoader("main_window_files", str(ROOT / "app" / "window" / "main.pyw"))
        spec = importlib.util.spec_from_loader("main_window_files", loader)
        self.web = importlib.util.module_from_spec(spec)
        loader.exec_module(self.web)
        self.path = Path(tempfile.mkdtemp()) / "notes.md"
        self.path.write_text("секретный рецепт", encoding="utf-8")
        self.asked, self.recorded, self.done = [], [], threading.Event()
        window = self.web.WebCompanion
        self.state = types.SimpleNamespace(
            settings={"model": "local.gguf"}, busy=False, pending_text_prompts=[], speech_enabled=False, selected_model="",
            _state_lock=threading.RLock(), action_cancel=threading.Event(), _active_response=None, _activity="",
            _local_blocked=lambda model: False, _changed=lambda: None, _shown=window._shown, _attachment_budget=lambda model: 10_000,
            _record=lambda *args: self.recorded.append(args),
            ask_model=lambda prompt, images, voice: (self.asked.append((prompt, images)), self.done.set()))

    def test_the_model_gets_the_text_and_the_chat_only_the_card(self):
        result = self.web.WebCompanion._send_with_images(self.state, "что тут?", [], [str(self.path)])
        self.assertTrue(result["ok"])
        self.assertTrue(self.done.wait(5))
        self.assertEqual(self.recorded, [("user", "что тут?", [], [str(self.path)])])
        prompt, images = self.asked[0]
        self.assertTrue(prompt.startswith("что тут?\n\nПриложенные файлы:"))
        self.assertIn('<file name="notes.md">\nсекретный рецепт\n</file>', prompt)
        self.assertIsNone(images)

    def test_a_lone_file_shows_no_words_and_waits_in_the_queue_with_its_text(self):
        self.state.busy = True
        result = self.web.WebCompanion._send_with_images(self.state, "", [], [str(self.path)])
        self.assertTrue(result["queued"])
        text, _model, _images, _paths, files, prompt = self.state.pending_text_prompts[0]
        self.assertEqual(self.web.WebCompanion._shown(text), "")
        self.assertEqual(files, [str(self.path)])
        self.assertIn("секретный рецепт", prompt)


if __name__ == "__main__":
    unittest.main()

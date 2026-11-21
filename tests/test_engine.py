import hashlib
import importlib.machinery
import importlib.util
import io
import json
import queue
import re
import sqlite3
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.chat import engine as core
from app.tools import computer
from app.models import llama
from app.tools import preview
from app.tools import toolbox as tools
from app.models import integrations
from app.tools import ai_mark
from pptx.oxml.ns import qn

from PIL import Image

from app.tools.presentation import _normalize, choose_design, create_presentation, fit_bullets
from app.tools.research import language_of, usable_candidate

Core = core.CompanionCore


def fake_core(**fields):
    base = dict(events=queue.Queue(), action_cancel=threading.Event(), busy=False, settings={"ui_language": "ru"},
                messages=[{"role": "system", "content": "s"}], dialogue_items=[], _save_conversation=lambda: None,
                _chat_summary=lambda: "")
    base.update(fields)
    return types.SimpleNamespace(**base)


class SettingsDefaults(unittest.TestCase):
    def test_old_russian_default_prompt_becomes_english_but_own_prompt_stays(self):
        for old in core.OLD_SYSTEM_PROMPTS:
            self.assertEqual(Core._current_system_prompt(old), core.COMPANION_SYSTEM_PROMPT)
        self.assertEqual(Core._current_system_prompt("Будь пиратом."), "Будь пиратом.")
        self.assertEqual(Core._current_system_prompt(""), core.COMPANION_SYSTEM_PROMPT)
        self.assertTrue(core.COMPANION_SYSTEM_PROMPT.isascii())

    def test_ten_models_have_ports(self):
        self.assertGreaterEqual(1 + len(llama.EXTRA_PORTS), 10)
        self.assertNotIn(47870, llama.EXTRA_PORTS)


class ModelSettings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("piven_prompt_window", str(ROOT / "app" / "window" / "main.pyw"))
        cls.web = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(cls.web)

    def test_prompts_are_saved_by_model_and_an_empty_prompt_restores_the_builtin_default(self):
        strata = "strata:local-model"
        unsloth = "unsloth:org/Qwen:Q4"
        app = Core()
        app._state_lock = threading.RLock()
        app._changed = mock.Mock()
        app._messages = [{"role": "system", "content": ""}]
        api = self.web.WebApi(app)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"system_prompt": "Общий промпт", "theme_revision": 2}), encoding="utf-8")
            with mock.patch.object(core, "SETTINGS_PATH", path), mock.patch.object(core, "THINKING_LEVELS", {}), \
                    mock.patch.multiple(llama, model_params={}, max_loaded=[3]), \
                    mock.patch.multiple(integrations, config={}, learned={}, on_learned=None), mock.patch.object(core.mcp, "configure"):
                app._load_settings()
                self.assertEqual(app._system_prompt_for_model(strata), core.COMPANION_SYSTEM_PROMPT)
                self.assertEqual(api.model_params(strata)["systemPrompt"], "")
                self.assertFalse(api.update_settings({"systemPrompt": "Replace all prompts"})["ok"])
                self.assertTrue(api.set_model_prompt(strata, "  Сначала выведи ответ.\nЗатем пояснение.  ")["ok"])
                self.assertTrue(api.set_model_prompt(unsloth, "Use short sentences.")["ok"])
                app._load_settings()
                self.assertEqual(api.model_params(strata)["systemPrompt"], "Сначала выведи ответ.\nЗатем пояснение.")
                self.assertEqual(api.model_params(unsloth)["systemPrompt"], "Use short sentences.")
                self.assertFalse(api.set_model_prompt(strata, "x" * (core.MAX_SYSTEM_PROMPT_LENGTH + 1))["ok"])
                with mock.patch.object(app, "_save_settings", return_value=False):
                    self.assertFalse(api.set_model_prompt(unsloth, "New prompt")["ok"])
                    self.assertEqual(api.model_params(unsloth)["systemPrompt"], "Use short sentences.")
                self.assertTrue(api.set_model_prompt(strata, " \n ")["ok"])
                app._load_settings()
                self.assertEqual(app._system_prompt_for_model(strata), core.COMPANION_SYSTEM_PROMPT)
                self.assertEqual(app._system_prompt_for_model(unsloth), "Use short sentences.")
                persisted = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotIn("system_prompt", persisted)
                self.assertEqual(persisted["legacy_system_prompt"], "Общий промпт")

    def test_model_parameters_survive_reload_without_inheriting_legacy_shared_values(self):
        local, remote = "local.gguf", "strata:local-model"
        app = Core()
        app._state_lock = threading.RLock()
        app._changed = mock.Mock()
        api = self.web.WebApi(app)
        original = {"*": {"temperature": 0.1}, local: {"top_k": 17}, remote: {"temperature": 0.3}, "invalid": [1]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"model_params": original, "theme_revision": 2}), encoding="utf-8")
            with mock.patch.object(core, "SETTINGS_PATH", path), mock.patch.object(core, "THINKING_LEVELS", {}), \
                    mock.patch.multiple(llama, model_params={}, max_loaded=[3]), \
                    mock.patch.multiple(integrations, config={}, learned={}, on_learned=None), mock.patch.object(core.mcp, "configure"):
                app._load_settings()
                self.assertEqual(api.model_params(local)["own"], {"top_k": 17})
                self.assertEqual(llama.params_for(local)["temperature"], llama.DEFAULT_PARAMS["temperature"])
                self.assertFalse(api.set_model_params("*", {"temperature": 0.2})["ok"])
                self.assertTrue(api.set_model_params(local, {"min_p": 0.4})["ok"])
                self.assertTrue(api.set_model_params(local, {"top_k": None})["ok"])
                with mock.patch.object(app, "_save_settings", return_value=False):
                    self.assertFalse(api.set_model_params(remote, {"temperature": 0.9})["ok"])
                    self.assertEqual(llama.params_for(remote)["temperature"], 0.3)
                app._load_settings()
                self.assertEqual(api.model_params(local)["own"], {"min_p": 0.4})
                self.assertEqual(api.model_params(remote)["own"], {"temperature": 0.3})
                self.assertEqual(app.settings["legacy_model_params"], original["*"])
                self.assertNotIn("*", app.settings["model_params"])
                self.assertTrue(api.set_model_params(local, {}, replace=True)["ok"])
                self.assertEqual(llama.params_for(local), llama.DEFAULT_PARAMS)
                self.assertEqual(llama.params_for(remote)["temperature"], 0.3)

    def test_each_request_uses_its_model_prompt_without_replacing_chat_history(self):
        app = Core()
        app.settings = {"model": "unsloth:model", "legacy_system_prompt": "Shared prompt.",
                        "model_system_prompts": {"strata:model": "Strata prompt.", "unsloth:model": "Unsloth prompt."},
                        "memory_enabled": False, "tools_enabled": False}
        app._messages = [{"role": "system", "content": "Previous prompt."}]
        app._chat_cancels, app._live_messages, app._live_turns = {}, {}, {}
        app.active_chat_id = "chat"
        app.chats = []
        app.running = False
        app.events = queue.Queue()
        with mock.patch.object(core, "model_chat", return_value="A reply.") as send:
            for model, expected in (("strata:model", "Strata prompt."), ("unsloth:model", "Unsloth prompt."),
                                    ("custom:other", core.COMPANION_SYSTEM_PROMPT)):
                with self.subTest(model=model):
                    app.selected_model = model
                    app.ask_model("Can you help?", None, False)
                    requested_model, messages = send.call_args.args
                    self.assertEqual(requested_model, model)
                    self.assertTrue(messages[0]["content"].startswith(expected + "\n\n"))
                    self.assertIn(core.COMPANION_SYSTEM_GUARDRAILS, messages[0]["content"])
        self.assertEqual([item["content"] for item in app.messages[1:]], ["Can you help?", "A reply."] * 3)


class EngineRemoval(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.voice = Path(temp.name) / "voice-engines"
        self.engines = self.voice / "engines"
        for folder in (self.engines / "kokoro", self.engines / "audiocpp" / "bin", self.engines / "audiocpp" / "models", self.voice / ".venv", self.voice / "nemo-speech"):
            folder.mkdir(parents=True)
            (folder / "file.bin").write_bytes(b"12345")
        (self.voice / core.install.NEMO_ZIP).write_bytes(b"123")
        install = core.install
        for patcher in (mock.patch.object(install, "VOICE_DIR", self.voice), mock.patch.object(install, "ASR_DIR", self.voice / "nemo-speech"),
                        mock.patch.object(install, "TTS_DIR", self.voice / "qwen-tts"),
                        mock.patch.object(install.voice_engines, "ENGINES_DIR", self.engines), mock.patch.object(install.voice_engines, "SHARED_VENV", self.voice / ".venv")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def use(self, *engines):
        patcher = mock.patch.object(core.install, "_engines_in_use", return_value=set(engines))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unused_engine_is_deleted_and_used_one_is_refused(self):
        self.use("audiocpp")
        self.assertEqual(core.install.delete_engine("kokoro"), 5)
        self.assertFalse((self.engines / "kokoro").exists())
        with self.assertRaisesRegex(RuntimeError, "нужен"):
            core.install.delete_engine("audiocpp")
        self.assertTrue((self.engines / "audiocpp" / "bin").exists())

    def test_shared_packages_stay_while_a_python_engine_is_used(self):
        self.use("transformers")
        with self.assertRaisesRegex(RuntimeError, "нужен"):
            core.install.delete_engine("shared")
        self.assertTrue((self.voice / ".venv").exists())

    def test_unknown_name_cannot_reach_other_folders(self):
        self.use()
        for name in ("..", "../..", "models", ""):
            with self.assertRaisesRegex(RuntimeError, "Неизвестный"):
                core.install.delete_engine(name)

    def test_nemo_goes_with_its_archive_and_audiocpp_keeps_models(self):
        self.use()
        self.assertEqual(core.install.delete_engine("nemo"), 8)
        self.assertFalse((self.voice / core.install.NEMO_ZIP).exists())
        core.install.delete_engine("audiocpp")
        self.assertFalse((self.engines / "audiocpp" / "bin").exists())
        self.assertTrue((self.engines / "audiocpp" / "models" / "file.bin").exists())


class VoiceDefaults(unittest.TestCase):
    def setUp(self):
        from app.voice import catalog
        self.original_catalog_search = catalog.search
        patcher = mock.patch.object(catalog, "search", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_engine_note_appears_only_when_engine_is_missing(self):
        with mock.patch.object(core.install.voice_engines, "ready", return_value=True):
            self.assertEqual(core.install.engine_note("nemo"), "")
        with mock.patch.object(core.install.voice_engines, "ready", return_value=False), mock.patch.object(core.install.voice_engines, "shared_ready", return_value=False):
            self.assertIn("GitHub", core.install.engine_note("nemo"))
            self.assertIn("PyTorch", core.install.engine_note("kokoro"))

    def test_search_queries_gguf_and_preserves_the_next_page(self):
        install = core.install
        def page(path, token, **options):
            self.assertIn("filter=gguf", path)
            self.assertIn("filter=automatic-speech-recognition", path)
            self.assertIn("sort=createdAt", path)
            self.assertIn("cursor=older", path)
            options["next_page"].append("next")
            return [
                {"id": "someone/new-asr", "tags": ["gguf"], "likes": 0},
                {"id": "someone/another-asr", "tags": ["gguf"], "likes": 0},
                {"id": "someone/onnx-only", "tags": ["onnx"]},
            ]

        next_page = []
        with mock.patch.object(install, "_hf_json", side_effect=page):
            hits = install.search("asr", "", recent=True, cursor="older", next_page=next_page)
        self.assertEqual([hit["id"] for hit in hits], ["someone/new-asr", "someone/another-asr"])
        self.assertEqual(next_page, ["next"])

    def test_direct_link_lists_gguf_variants_and_excludes_the_projector(self):
        install = core.install
        repo = "someone/NewASR"
        names = ["model-q4.gguf", "parts/model-q8_0.GGUF", "mmproj-model.gguf", "model.safetensors"]
        model = {"id": repo, "siblings": [{"rfilename": name} for name in names]}
        with mock.patch.object(install, "_hf_json", return_value=model) as request:
            hit, = install.search("asr", f"https://huggingface.co/{repo}/blob/main/config.json", "token")
        request.assert_called_once_with(f"/api/models/{repo}", "token")
        self.assertEqual((hit["engine"], hit["problem"], hit["direct"]), ("auto", "", True))
        with mock.patch.object(install, "_repo_files", return_value=[{"path": name} for name in names]):
            info = install._details("asr", repo, "nemo")
        self.assertEqual([item["path"] for item in info["files"]], [names[1], names[0]])

    def test_unmapped_tts_ggufs_are_listed_for_file_compatibility_check(self):
        model = {"id": "someone/new-tts", "tags": ["gguf"], "pipeline_tag": "text-to-speech"}
        with mock.patch.object(core.install, "_hf_json", return_value=[model]) as request:
            hit, = core.install.search("tts", "", recent=True)
        self.assertIn("filter=text-to-speech", request.call_args.args[0])
        self.assertEqual(hit["id"], model["id"])
        self.assertEqual(hit["engine"], "auto")
        self.assertFalse(hit.get("problem"))

    def test_direct_model_lookup_explains_other_formats(self):
        model = {"id": "someone/only-onnx", "tags": ["onnx"], "siblings": [{"rfilename": "onnx/model.onnx"}]}
        with mock.patch.object(core.install, "_hf_json", return_value=model):
            hit, = core.install.search("asr", "someone/only-onnx")
        self.assertTrue(hit["direct"])
        self.assertIn("GGUF", hit["problem"])

    def test_legacy_models_stay_in_disk_inventory_but_cannot_be_chosen(self):
        install = core.install
        legacy = {"engine": "qwen", "title": "Legacy TTS", "bytes": 42}
        with mock.patch.object(install, "tts_catalogue", return_value={"legacy": legacy}), \
             mock.patch.object(install, "asr_catalogue", return_value={}), \
             mock.patch.object(install, "_tts_installed", return_value=True), \
             mock.patch.object(install, "_engines_in_use", return_value=set()):
            self.assertEqual(install.chosen_model("tts", "legacy"), "")
            self.assertFalse(install.ready("tts", "legacy"))
            self.assertEqual(install.status()["tts"]["models"], [])
            self.assertEqual(install.disk_usage()["legacy"], [{"id": "legacy", "kind": "tts", "title": "Legacy TTS", "bytes": 42}])

    def test_popular_search_falls_back_to_builtin_ggufs(self):
        warnings = []
        with mock.patch.object(core.install, "_hf_json", side_effect=TimeoutError("slow")):
            hits = core.install.search("asr", "", warnings=warnings)
        self.assertIn("не загрузился", warnings[0])
        self.assertEqual({item["engine"] for item in hits}, {"nemo"})

    def test_installer_rejects_legacy_formats_and_checks_selected_gguf(self):
        from app.models import memory_fit
        install = core.install
        with self.assertRaisesRegex(ValueError, "GGUF"):
            install.validate_install("tts", "Qwen/voice", {"engine": "qwen"})
        with self.assertRaisesRegex(ValueError, "GGUF"):
            install.validate_install("asr", "someone/voice", {"engine": "nemo", "file": {"path": "model.safetensors"}})
        extra = {"engine": "nemo", "file": {"path": "voice-q4.gguf"}}
        with mock.patch.object(memory_fit, "remote_metadata", return_value={"general.architecture": "llama"}), \
             mock.patch.object(install, "install_asr") as download:
            with self.assertRaisesRegex(ValueError, "llama"):
                install.install("asr", "someone/voice", None, None, extra)
        download.assert_not_called()

    def test_official_asr_uses_pinned_artifact_when_repo_listing_fails(self):
        install = core.install
        source = install.ASR_MODELS["parakeet-ctc"]
        with mock.patch.object(install, "_hf_json", side_effect=TimeoutError):
            hit, = install.search("asr", source["repo"])
        with mock.patch.object(install, "_repo_files", side_effect=TimeoutError):
            details = install._details("asr", hit["id"], hit["engine"])
        file, = details["files"]
        self.assertEqual(file, {"path": source["file"], "size": source["bytes"]})
        progress = lambda *_: None
        cancel = threading.Event()
        with mock.patch.object(install, "ASR_EXE", mock.Mock()), \
             mock.patch.object(install, "_asr_installed", return_value=False), \
             mock.patch.object(install, "_download") as download:
            result = install.install("asr", hit["id"], progress, cancel, {"engine": "nemo", "file": file})
        self.assertEqual(result, "parakeet-ctc")
        url, _, size, checksum = download.call_args.args[:4]
        self.assertTrue(url.endswith(f"/resolve/{source['revision']}/{source['file']}"))
        self.assertEqual((size, checksum), (source["bytes"], source["sha256"]))

    def test_asr_checks_downloaded_header_if_remote_read_fails(self):
        from app.models import memory_fit
        install = core.install
        repo = "someone/voice"
        filename = "model.gguf"

        def gguf_string(value):
            value = value.encode()
            return struct.pack("<Q", len(value)) + value

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for architecture in ("parakeet-ctc", "llama"):
                with self.subTest(architecture=architecture):
                    header = b"GGUF" + struct.pack("<IQQ", 3, 0, 1)
                    header += gguf_string("general.architecture") + struct.pack("<I", 8) + gguf_string(architecture)
                    extra = {"engine": "auto", "file": {"path": filename, "size": len(header)}}
                    destination = root / architecture / "someone--voice" / filename

                    with mock.patch.object(install, "ASR_EXE", mock.Mock()), \
                         mock.patch.object(install, "ASR_MODELS_DIR", root), \
                         mock.patch.object(install, "CUSTOM_ASR_DIR", root / architecture), \
                         mock.patch.object(memory_fit, "remote_metadata", return_value={}), \
                         mock.patch.object(install.download, "fetch") as fetch:
                        def receive(url, partial, *_, **_options):
                            partial.parent.mkdir(parents=True, exist_ok=True)
                            return partial.write_bytes(header)
                        fetch.side_effect = receive
                        if architecture == "parakeet-ctc":
                            self.assertEqual(install.install("asr", repo, lambda *_: None, threading.Event(), extra),
                                             f"hf:{repo}/{filename}")
                            self.assertEqual(destination.read_bytes(), header)
                        else:
                            with self.assertRaisesRegex(ValueError, "llama"):
                                install.install("asr", repo, lambda *_: None, threading.Event(), extra)
                            self.assertFalse(destination.exists())
                            self.assertFalse(destination.with_suffix(".gguf.download").exists())

    def test_asr_keeps_original_files_alongside_a_matching_audiocpp_package(self):
        from app.voice import catalog
        install = core.install
        repo = "handy-computer/Voxtral-Mini-4B-Realtime-2602-gguf"
        spec = {"tasks": ["asr"], "display_name": "Voxtral", "packages": [{
            "format": "gguf", "files": ["voxtral.gguf"], "target_directory": "Voxtral-Mini-4B-Realtime-2602-GGUF",
        }]}
        item = {"id": repo, "tags": ["gguf"]}
        with mock.patch.object(catalog, "search", wraps=self.original_catalog_search), \
             mock.patch.object(catalog, "specs", return_value={"voxtral_realtime": spec}), \
             mock.patch.object(install, "_hf_json", side_effect=[item, [item]]):
            direct, package = install.search("asr", repo)
            self.assertEqual((direct["id"], direct["engine"], direct["direct"]), (repo, "auto", True))
            self.assertEqual((package["id"], package["engine"]), ("audiocpp:voxtral_realtime", "audiocpp"))
            hits = install.search("asr", "voxtral", recent=True)
            self.assertEqual([row["id"] for row in hits], [package["id"], repo])

    def test_whisper_gguf_routes_to_transcribe_and_is_selectable_after_install(self):
        from app.models import memory_fit
        install = core.install
        repo = "third-party/speech-checkpoints"
        item = {"id": repo, "tags": ["gguf"], "pipeline_tag": "automatic-speech-recognition"}
        header = {"general.architecture": "whisper", "stt.variant": "large-v3"}
        with mock.patch.object(install, "_hf_json", side_effect=[item, [item]]):
            direct, = install.search("asr", repo)
            listed, = install.search("asr", "whisper", recent=True)
        self.assertEqual((direct["engine"], listed["engine"]), ("auto", "auto"))
        extra = {"engine": "auto", "file": {"path": "whisper-large-v3-Q8_0.gguf", "size": 4}}

        def receive(url, partial, *_, **_options):
            self.assertIn(f"/{repo}/resolve/main/", url)
            partial.parent.mkdir(parents=True)
            return partial.write_bytes(b"GGUF")

        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(install, "ASR_MODELS_DIR", Path(folder)), \
             mock.patch.object(install, "REGISTRY_PATH", Path(folder) / "voice.json"), \
             mock.patch.object(install.voice_engines, "ensure_transcribe", return_value=20), \
             mock.patch.object(install.voice_engines, "ready", return_value=True), \
             mock.patch.object(memory_fit, "remote_metadata", return_value=header), \
             mock.patch.object(memory_fit, "local_metadata", return_value=header), \
             mock.patch.object(install, "repo_license", return_value="Apache 2.0"), \
             mock.patch.object(install.download, "fetch", side_effect=receive), \
             mock.patch.object(install, "_install_nemo") as install_nemo:
            checked = install.check_file("asr", repo, extra["file"]["path"])
            self.assertEqual((checked["engine"], checked["engineName"]), ("transcribe", "transcribe.cpp"))
            model_id = install.install("asr", repo, lambda *_: None, threading.Event(), extra)
            self.assertTrue(install.ready("asr", model_id))
            self.assertEqual(install.chosen_model("asr", model_id), model_id)
            self.assertEqual(install.asr_model_path(model_id).read_bytes(), b"GGUF")
            install_nemo.assert_not_called()

    def test_engine_selection_uses_each_file_and_requested_voice_task(self):
        from app.models import memory_fit
        from app.voice import catalog
        install = core.install
        headers = {
            "asr.gguf": {"general.architecture": "asr", "asr.head_type": "tdt"},
            "whisper.gguf": {"general.architecture": "whisper"},
            "tts.gguf": {"general.architecture": "audiocpp", "audiocpp.model_spec.family": "qwen3_tts"},
            "text.gguf": {"general.architecture": "llama"},
            "missing.gguf": {},
        }
        specs = {"qwen3_tts": {"tasks": ["tts"], "packages": [{"id": "package", "format": "gguf",
                  "files": ["models/weights.gguf"], "download": {"repo": "example/packaged"}}]}}
        with mock.patch.object(catalog, "specs", return_value=specs), \
             mock.patch.object(memory_fit, "remote_metadata", side_effect=lambda repo, path, *_, **_options: headers[path]) as probe:
            for kind, path, engine in (("asr", "asr.gguf", "nemo"), ("asr", "whisper.gguf", "transcribe"),
                                       ("tts", "tts.gguf", "audiocpp"), ("tts", "whisper.gguf", ""),
                                       ("asr", "text.gguf", ""), ("asr", "missing.gguf", "")):
                with self.subTest(kind=kind, path=path):
                    result = install.check_file(kind, "example/mixed", path)
                    self.assertEqual((result["supported"], result["engine"]), (bool(engine), engine))
                    self.assertEqual(result["retryable"], path == "missing.gguf")
            probe.reset_mock()
            self.assertEqual(install.check_file("tts", "example/packaged", "models/weights.gguf")["engine"], "audiocpp")
            probe.assert_not_called()

    def test_automatic_tts_install_keeps_required_sidecars_with_the_selected_file(self):
        from app.models import memory_fit
        from app.voice import catalog
        install = core.install
        repo, filename = "example/tts", "voices/weights.gguf"
        header = {"general.architecture": "audiocpp", "audiocpp.model_spec.family": "test_tts",
                  "audiocpp.embedded_files.names": ["tokenizer.json"]}
        spec = {"tasks": ["tts"], "sources": [{"format": "gguf", "files": {
            "config": "model:config.json", "tokenizer": "model:tokenizer.json"}}]}
        files = [{"path": "voices/config.json", "size": 2}, {"path": filename, "size": 4}]

        def receive(url, partial, *_, **_options):
            partial.parent.mkdir(parents=True, exist_ok=True)
            return partial.write_bytes(b"GGUF" if url.endswith(filename) else b"{}")

        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(catalog, "specs", return_value={"test_tts": spec}), \
             mock.patch.object(install, "_repo_files", return_value=files), \
             mock.patch.object(install, "ASR_MODELS_DIR", Path(folder)), \
             mock.patch.object(install, "REGISTRY_PATH", Path(folder) / "voice.json"), \
             mock.patch.object(install, "repo_license", return_value="MIT"), \
             mock.patch.object(install.voice_engines, "ensure_audiocpp", return_value=0), \
             mock.patch.object(memory_fit, "remote_metadata", return_value=header), \
             mock.patch.object(memory_fit, "local_metadata", return_value=header), \
             mock.patch.object(install.download, "fetch", side_effect=receive) as fetch:
            self.assertEqual(install.check_file("tts", repo, filename)["engine"], "audiocpp")
            selected = install.install("tts", repo, lambda *_: None, threading.Event(),
                                        {"engine": "auto", "file": {"path": filename, "size": 4}})
            info = install.tts_model(selected)
            self.assertEqual((info["task"], info["family"], info["bytes"]), ("tts", "test_tts", 6))
            self.assertEqual(info["path"].with_name("config.json").read_bytes(), b"{}")
            self.assertEqual(fetch.call_count, 2)

    def test_short_voice_download_resumes_at_the_received_offset(self):
        install = core.install
        responses = [io.BytesIO(b"abc"), io.BytesIO(b"def")]
        responses[0].status, responses[0].headers = 200, {}
        responses[1].status, responses[1].headers = 206, {"Content-Range": "bytes 3-5/6"}
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(urllib.request, "urlopen", side_effect=responses) as request, \
             mock.patch.object(time, "monotonic", side_effect=[0, 3]):
            target = Path(folder) / "voice.gguf"
            install._download("https://example.test/voice.gguf", target, 6, "", threading.Event(), lambda *_: None)
            self.assertEqual(target.read_bytes(), b"abcdef")
            self.assertEqual(request.call_args.args[0].get_header("Range"), "bytes=3-")

    def test_multifile_audiocpp_packages_are_selectable(self):
        install = core.install
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "voice.gguf").write_bytes(b"weights")
            info = {"engine": "audiocpp", "path": str(path), "title": "GGUF voice"}
            registry = {"asr": {}, "tts": {"audiocpp:family/pkg": info}}
            with mock.patch.object(install, "_registry", return_value=registry):
                self.assertEqual(install.chosen_model("tts"), "audiocpp:family/pkg")

    def test_nothing_downloaded_means_nothing_chosen_or_listed(self):
        with mock.patch.object(core.install, "_asr_installed", return_value=False), mock.patch.object(core.install, "_tts_installed", return_value=False):
            self.assertEqual(core.install.chosen_model("asr"), "")
            self.assertEqual(core.install.chosen_model("tts", core.install.DEFAULT_TTS), "")
            status = core.install.status()
        self.assertEqual((status["asr"]["models"], status["tts"]["models"]), ([], []))

    def test_only_downloaded_models_are_listed_and_saved_choice_survives(self):
        with mock.patch.object(core.install, "_asr_installed", side_effect=lambda key: key in ("nemotron-en", "parakeet-ctc")):
            self.assertEqual(core.install.chosen_model("asr", "nemotron-en"), "nemotron-en")
            self.assertEqual(core.install.chosen_model("asr", core.install.DEFAULT_ASR), "parakeet-ctc")
            self.assertEqual({row["id"] for row in core.install.status()["asr"]["models"]}, {"nemotron-en", "parakeet-ctc"})


class HeavyMode(unittest.TestCase):
    def core(self, heavy=True, **fields):
        engine = Core.__new__(Core)
        base = dict(events=queue.Queue(), settings={"heavy_mode": heavy, "max_loaded_models": 5, "model": "big"}, running=False, stop_event=threading.Event(),
                    tts_cancel=threading.Event(), tts_generation=0, asr_process=None, tts_process=None, comfy_process=None,
                    dictation={"session": 0, "phase": "", "text": ""}, _dictation_stop=threading.Event(), _dictation_thread=None)
        base.update(fields)
        engine.__dict__.update(base)
        return engine

    def setUp(self):
        patcher = mock.patch.object(llama, "max_loaded", [3])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_voice_and_images_refuse_and_speech_preference_survives(self):
        engine = self.core()
        engine.speech_enabled = True
        self.assertFalse(engine.speech_enabled)
        self.assertEqual(engine.voice_vram(), 0)
        self.assertIn("тяжёлых", engine.start_dictation())
        self.assertIn("тяжёлых", engine.start_listening((True, False, False, False), "big"))
        for start in (engine._ensure_asr, engine._ensure_tts, lambda: engine._ensure_comfyui("http://127.0.0.1:8188")):
            with self.assertRaisesRegex(RuntimeError, "тяжёлых"):
                start()
        engine.settings["heavy_mode"] = False
        self.assertTrue(engine.speech_enabled)

    def test_only_chosen_model_stays_and_turning_off_restores_the_limit(self):
        chosen = types.SimpleNamespace(loaded_model="big", in_use=False, stop=mock.Mock())
        other = types.SimpleNamespace(loaded_model="small", in_use=False, stop=mock.Mock())
        answering = types.SimpleNamespace(loaded_model="third", in_use=True, stop=mock.Mock())
        asr, tts = mock.Mock(), mock.Mock()
        engine = self.core(asr_process=asr, tts_process=tts)
        started = []
        real_thread = threading.Thread
        def run_now(target, daemon=None):
            started.append(target)
            return types.SimpleNamespace(start=target)
        with mock.patch.object(llama, "SERVERS", [chosen, other, answering]), mock.patch.object(core.mcp, "stop_all") as stop_mcp, mock.patch.object(core.threading, "Thread", run_now):
            engine.apply_heavy_mode()
        self.assertEqual(llama.max_loaded[0], 1)
        chosen.stop.assert_not_called(); answering.stop.assert_not_called(); other.stop.assert_called_once()
        stop_mcp.assert_called_once()
        self.assertIsNone(engine.asr_process); self.assertIsNone(engine.tts_process)
        engine.settings["heavy_mode"] = False
        engine.apply_heavy_mode()
        self.assertEqual(llama.max_loaded[0], 5)

    def test_toolbox_skips_web_and_mcp(self):
        with tempfile.TemporaryDirectory() as folder:
            server = mock.Mock(_tools=None, tools=mock.Mock(return_value=[]))
            with mock.patch.dict(core.mcp.servers, {"x": server}):
                specs = tools.ToolBox(Path(folder), Path(folder), None, use_mcp=False).specs()
        server.tools.assert_not_called()
        self.assertNotIn("web_search", [spec["function"]["name"] for spec in specs])


class Dictation(unittest.TestCase):
    def core(self, **fields):
        engine = Core.__new__(Core)
        base = dict(events=queue.Queue(), settings={"asr_model": "m"}, running=False, asr_process=types.SimpleNamespace(poll=lambda: None), asr_lock=threading.Lock(),
                    dictation={"session": 0, "phase": "", "text": ""}, _dictation_stop=threading.Event(), _dictation_thread=None, mic_device="", mic_sensitivity=50)
        base.update(fields)
        engine.__dict__.update(base)
        return engine

    def run_session(self, levels, words):
        import numpy as np
        engine = self.core()
        phases = []
        phase = engine._dictation_phase
        engine._dictation_phase = lambda value: (phases.append(value), phase(value))
        blocks = list(levels)

        class Recorder:
            def __enter__(self): return self
            def __exit__(self, *error): return False
            def record(self, numframes):
                level = blocks.pop(0)
                if not blocks:
                    engine._dictation_stop.set()
                return np.full((numframes, 1), level, dtype="float32")

        mic = types.SimpleNamespace(recorder=lambda **options: Recorder())
        card = types.SimpleNamespace(default_microphone=lambda: mic)
        answers = iter(words)
        with mock.patch.dict(sys.modules, {"soundcard": card}), mock.patch.object(core.install, "ready", return_value=True), mock.patch.object(core.install, "asr_model", return_value={"language": "ru"}), \
                mock.patch.object(core, "parakeet_transcribe", side_effect=lambda *args: next(answers)), mock.patch.object(core, "DICTATION_KEEP_SECONDS", 60), \
                mock.patch.object(Core, "_ensure_asr", return_value=engine.asr_process):
            self.assertEqual(engine.start_dictation(), "")
            engine._dictation_thread.join(timeout=10)
        return engine, phases

    def test_pause_splits_phrases_and_stop_keeps_the_tail(self):
        engine, phases = self.run_session([0, 0, .5, .5, .5, .5, 0, 0, 0, 0, .5, .5], ["первая фраза", "вторая"])
        self.assertEqual(engine.dictation["text"], "первая фраза вторая")
        self.assertEqual(phases, ["listening", ""])

    def test_silence_gives_no_text(self):
        engine, _ = self.run_session([0, 0, 0], [])
        self.assertEqual(engine.dictation["text"], "")
        self.assertEqual(engine.dictation["phase"], "")

    def test_call_keeps_the_microphone(self):
        self.assertIn("звонком", self.core(running=True).start_dictation())

    def test_missing_model_is_reported(self):
        with mock.patch.dict(sys.modules, {"soundcard": types.SimpleNamespace()}), mock.patch.object(core.install, "ready", return_value=False):
            self.assertIn("не скачана", self.core().start_dictation())


class ContextFitting(unittest.TestCase):
    def setUp(self):
        llama.model_params["m"] = {"ctx_size": 2560, "compress_context": False}

    def tearDown(self):
        llama.model_params.pop("m", None)

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


class TokenCounting(unittest.TestCase):
    def tearDown(self):
        llama._tokenize.cache_clear()

    def serve(self, reply):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_loaded_model_counts_exactly(self):
        fake = types.SimpleNamespace(loaded_model="m", base_url=self.serve(b'{"tokens":[1,2,3,4]}'))
        with mock.patch.object(llama, "SERVERS", [fake]):
            self.assertEqual(llama.count_tokens("m", "any long text here"), 4)

    def test_unloaded_or_broken_model_falls_back_to_the_estimate(self):
        self.assertEqual(llama.count_tokens("not-loaded", "x" * 30), 10)
        fake = types.SimpleNamespace(loaded_model="m", base_url=self.serve(b"not json"))
        with mock.patch.object(llama, "SERVERS", [fake]):
            self.assertEqual(llama.count_tokens("m", "x" * 30), 10)

    def test_unloaded_model_uses_the_tokenizer_only_when_asked(self):
        llama._tokenize_unloaded.cache_clear()
        finished = types.SimpleNamespace(stdout="Total number of tokens: 7\n", stderr="")
        with mock.patch.object(llama, "model_files", return_value={"m": (Path("m.gguf"), None)}), \
                mock.patch.object(llama, "TOKENIZE_EXE", Path(__file__)), \
                mock.patch.object(llama.subprocess, "run", return_value=finished) as run:
            self.assertEqual(llama.count_tokens("m", "x" * 30, unloaded=True), 7)
            self.assertEqual(llama.count_tokens("m", "x" * 30), 10)
            self.assertEqual(run.call_count, 1)
        llama._tokenize_unloaded.cache_clear()

    def test_failed_tokenizer_falls_back_to_the_estimate(self):
        llama._tokenize_unloaded.cache_clear()
        broken = types.SimpleNamespace(stdout="boom", stderr="")
        with mock.patch.object(llama, "model_files", return_value={"m": (Path("m.gguf"), None)}), \
                mock.patch.object(llama, "TOKENIZE_EXE", Path(__file__)), \
                mock.patch.object(llama.subprocess, "run", return_value=broken):
            self.assertEqual(llama.count_tokens("m", "x" * 30, unloaded=True), 10)

    def test_estimate_does_not_undercount_chinese(self):
        self.assertGreater(llama.estimate_tokens("你好世界" * 100), 200)
        self.assertEqual(llama.count_tokens("not-loaded", ""), 0)


class Polls(unittest.TestCase):
    def test_model_is_told_the_date(self):
        self.assertIn(core.datetime.now().strftime("%Y-%m-%d"), core.CompanionCore._date_rule())


    def test_full_form_keeps_descriptions_and_one_recommendation(self):
        questions = tools.poll_questions({"questions": [{"question": " Куда? ", "multiple": True, "options": [
            {"label": "A", "description": "первый", "recommended": True}, {"label": "B", "recommended": True}, {"label": "A"}]}]})
        self.assertEqual(questions[0]["question"], "Куда?")
        self.assertTrue(questions[0]["multiple"])
        self.assertEqual([option["recommended"] for option in questions[0]["options"]], [True, False])
        self.assertEqual(questions[0]["options"][0]["description"], "первый")

    def test_poll_leaves_a_note_for_the_next_turn(self):
        shown = []
        box = tools.ToolBox("no-app", "no-data", on_poll=shown.append)
        box.run("create_poll", {"questions": [{"question": "Куда?", "options": ["A", "B"]}]})
        self.assertTrue(box.turn_over)
        self.assertEqual(shown[0]["questions"][0]["question"], "Куда?")
        self.assertIn(tools.POLL_NOTE, box.poll_note)
        self.assertIn("Куда?", box.poll_note)

    def test_old_flat_form_and_too_few_options(self):
        self.assertEqual([option["label"] for option in tools.poll_questions({"question": "Q", "options": ["a", "b"]})[0]["options"]], ["a", "b"])
        self.assertEqual(tools.poll_questions({"question": "Q", "options": ["a"]}), [])
        self.assertEqual(len(tools.poll_questions({"questions": [{"question": "Q", "options": ["a", "b"]}] * 6})), 4)


class Presentation(unittest.TestCase):
    def test_slide_without_points_becomes_a_section(self):
        slides = _normalize([{"title": "A", "layout": "cards", "bullets": []}])
        self.assertEqual(slides[0]["layout"], "section")

    def test_points_written_as_text_and_too_many_points(self):
        slides = _normalize([{"title": "A", "content": "- one\n- two"}, {"title": "B", "bullets": [str(i) for i in range(12)]}])
        self.assertEqual(slides[0]["bullets"], ["one", "two"])
        self.assertEqual(len(slides[1]["bullets"]), 8)

    def test_fallback_look_understands_other_languages(self):
        for title, preset in (("The history of video games", "paper"), ("Exploring Mars", "royal"), ("Historia de Roma", "paper"),
                              ("La vida en el océano", "ocean"), ("人工智能的未来", "neon"), ("海洋的秘密", "ocean"), ("Quarterly research", "ocean")):
            self.assertEqual(choose_design(None, title, [])["name"], preset, title)

    def test_slide_repeating_the_cover_is_dropped_or_renamed(self):
        from pptx import Presentation as Deck
        with tempfile.TemporaryDirectory() as folder:
            empty = create_presentation("Марс: планета", [{"title": "марс — планета", "layout": "section"}, {"title": "Орбита", "bullets": ["a"]}], output_root=folder, language="ru")
            self.assertEqual(len(Deck(str(empty)).slides), 2)
            full = create_presentation("Марс", [{"title": "Марс", "bullets": ["a"]}], output_root=folder, language="ru")
            texts = [shape.text_frame.text for shape in Deck(str(full)).slides[1].shapes if shape.has_text_frame]
            self.assertIn("Введение", texts)
            self.assertNotIn("Марс", texts[:-2])

    def test_long_points_shrink_to_fit_the_box(self):
        size, rows = fit_bullets(["слово " * 40] * 5, 6.3, 4.95)
        self.assertLess(size, 20)
        self.assertLessEqual(sum(rows), 4.95)

    def test_only_free_landscape_or_square_images_are_used(self):
        good = {"url": "https://x/a.jpg", "width": 1200, "height": 800, "mime": "image/jpeg", "license": "CC BY-SA 4.0"}
        self.assertTrue(usable_candidate(good))
        self.assertFalse(usable_candidate({**good, "license": "CC BY-NC 2.0"}))
        self.assertFalse(usable_candidate({**good, "license": ""}))
        self.assertFalse(usable_candidate({**good, "width": 300, "height": 300}))
        self.assertFalse(usable_candidate(good, {"https://x/a.jpg"}))

    def test_images_notes_and_sources_end_up_in_the_file(self):
        from pptx import Presentation as Deck
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        buffer = io.BytesIO()
        Image.new("RGB", (1200, 600), "red").save(buffer, "JPEG")
        image = {"data": buffer.getvalue(), "size": (1200, 600), "credit": "Author · CC BY 4.0 · Wikimedia Commons", "page": "https://commons/x"}
        with tempfile.TemporaryDirectory() as folder:
            path = create_presentation("T", [{"title": "A", "bullets": ["one"], "notes": "Say this", "image": image}], output_root=folder, cover_image=image,
                                       articles=[{"title": "Art", "url": "https://w/a", "text": ""}], language="en")
            cover, slide, sources = Deck(str(path)).slides
            for page in (cover, slide):
                self.assertEqual(sum(shape.shape_type == MSO_SHAPE_TYPE.PICTURE for shape in page.shapes), 1)
            self.assertEqual(slide.notes_slide.notes_text_frame.text, "Say this")
            text = " ".join(shape.text_frame.text for shape in sources.shapes if shape.has_text_frame)
            self.assertIn("Sources", text)
            self.assertIn("https://w/a", text)
            self.assertIn("https://commons/x", text)

    def test_request_language_picks_the_wikipedia(self):
        self.assertEqual([language_of(text) for text in ("Сделай презентацию", "Make slides", "做演示文稿", "Haz una presentación")], ["ru", "en", "zh", "es"])

    def test_chinese_text_gets_a_chinese_font_and_english_quotes_stay_english(self):
        from pptx import Presentation as Deck
        with tempfile.TemporaryDirectory() as folder:
            path = create_presentation("海洋的秘密", [{"title": "A", "layout": "quote", "quote": "To be"}], output_root=folder)
            cover, quote = Deck(str(path)).slides
            runs = [shape.text_frame.paragraphs[0].runs[0] for shape in cover.shapes if shape.has_text_frame and shape.text_frame.text == "海洋的秘密"]
            self.assertEqual(runs[0].font._element.find(qn("a:ea")).get("typeface"), "Microsoft YaHei")
            self.assertIn("“To be”", [shape.text_frame.text for shape in quote.shapes if shape.has_text_frame])


class ComputerCommands(unittest.TestCase):
    def test_unknown_command_lists_the_real_ones(self):
        with self.assertRaisesRegex(ValueError, "Команды «build_game» нет. Доступны: .*create_file"):
            computer.execute_computer_action({"computer_action": "build_game"})

    def test_invented_names_map_to_real_commands(self):
        self.assertEqual(computer._ACTION_ALIASES["save_file"], "write_file")
        self.assertEqual(computer._ACTION_ALIASES["mkdir"], "create_folder")
        self.assertTrue(set(computer._ACTION_ALIASES.values()) <= set(computer.COMPUTER_ACTIONS))

    def test_write_file_rewrites_only_what_this_request_made(self):
        with tempfile.TemporaryDirectory() as folder:
            old = Path(folder) / "old.txt"
            old.write_text("mine", encoding="utf-8")
            created = []
            computer._file_action("write_file", {"path": str(Path(folder) / "game.js"), "content": "a"}, created)
            computer._file_action("write_file", {"path": str(Path(folder) / "game.js"), "content": "b"}, created)
            self.assertEqual((Path(folder) / "game.js").read_text(encoding="utf-8"), "b")
            with self.assertRaisesRegex(ValueError, "нельзя перезаписать"):
                computer._file_action("write_file", {"path": str(old), "content": "x"}, created)
            self.assertEqual(old.read_text(encoding="utf-8"), "mine")

    def test_undo_deletes_only_unchanged_files_and_empty_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            created = []
            game = Path(folder) / "Game"
            computer._file_action("create_folder", {"path": str(game)}, created)
            computer._file_action("create_file", {"path": str(game / "a.js"), "content": "1"}, created)
            computer._file_action("create_file", {"path": str(game / "b.js"), "content": "2"}, created)
            record = Core._undo_record(created)
            (game / "b.js").write_text("changed by the user", encoding="utf-8")
            removed, kept = Core.undo_files(record)
            self.assertFalse((game / "a.js").exists())
            self.assertTrue((game / "b.js").exists())
            self.assertTrue(game.exists())
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
    def setUp(self):
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader("main_window", str(ROOT / "app" / "window" / "main.pyw"))
        spec = importlib.util.spec_from_loader("main_window", loader)
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


class MemoryModels(unittest.TestCase):
    def test_model_saved_facts_and_manual_facts_keep_their_source_in_an_existing_database(self):
        from contextlib import closing
        from app.chat.memory import Memory

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "memory").mkdir()
            with closing(sqlite3.connect(root / "memory" / "memory.sqlite")) as previous:
                previous.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, kind TEXT, chat_id TEXT, text TEXT, created REAL, vector BLOB)")
                previous.execute("INSERT INTO memories (kind, chat_id, text, created) VALUES ('fact', '', 'Old fact', 1)")
                previous.commit()

            memory = Memory(root, root / "server.exe")
            with closing(memory._db):
                toolbox = tools.ToolBox(root, root, memory=memory)
                memory.add("fact", "Manual fact", source="manual")
                memory.add_exchange("chat", "Some question", "Some answer")
                self.assertEqual(toolbox.run("remember", {"fact": "Model fact"}), "Запомнено.")
                self.assertEqual(toolbox.run("remember", {"fact": "Model fact"}), "Это уже есть в памяти.")
                self.assertEqual([(row["text"], row["source"]) for row in memory.facts()],
                                 [("Model fact", "model"), ("Manual fact", "manual"), ("Old fact", "")])

    def test_switch_removes_earlier_models_and_unfinished_downloads(self):
        from app.chat import memory
        with tempfile.TemporaryDirectory() as folder:
            models = Path(folder) / "model"
            models.mkdir()
            for name in ("old.gguf", "new.gguf", "broken.gguf.download", "chosen.txt", "notes.md"):
                (models / name).write_text("x", encoding="utf-8")
            memory.Memory._remove_other_models(types.SimpleNamespace(folder=Path(folder)), models / "new.gguf")
            self.assertEqual(sorted(item.name for item in models.iterdir()), ["chosen.txt", "new.gguf", "notes.md"])


class VoicePaths(unittest.TestCase):
    def test_models_saved_under_the_old_voice_folder_are_found_in_voice_engines(self):
        from app.voice import install
        old = install.APP_DIR / "voice" / "engines" / "audiocpp" / "models" / "x.gguf"
        with mock.patch.object(Path, "exists", lambda self: False):
            self.assertEqual(install._current_path(old), install.VOICE_DIR / "engines" / "audiocpp" / "models" / "x.gguf")
        elsewhere = Path("D:/models/y.gguf")
        with mock.patch.object(Path, "exists", lambda self: False):
            self.assertEqual(install._current_path(elsewhere), elsewhere)


class ThinkingLevels(unittest.TestCase):
    def test_template_that_thinks_only_with_its_own_prompt_gets_a_switch(self):
        template = r"{%- set default_system_message = 'Use [THINK]\n it\'s fine' %}"
        with mock.patch.object(llama, "_template", return_value=template), mock.patch.object(llama, "model_files", return_value={"m": ("p",)}):
            self.assertEqual(llama._thinking_prompt("m"), "Use [THINK]\n it's fine")
            self.assertEqual(llama.thinking_modes("m"), ([True, False], True))

    def test_word_thinking_in_a_template_does_not_mean_the_model_thinks(self):
        with mock.patch.object(llama, "_template", return_value="# HOW YOU SHOULD THINK"), mock.patch.object(llama, "model_files", return_value={"m": ("p",)}):
            self.assertEqual(llama.thinking_modes("m"), ([], False))

    def test_effort_levels_in_round_brackets(self):
        template = "{%- if reasoning_effort not in ('xhigh', 'medium', 'low') %}{%- set e = reasoning_effort|default('xhigh') %}"
        self.assertEqual(llama.effort_levels(template), (["low", "medium", "xhigh"], "xhigh"))

    def test_switch_only_template_gets_budget_levels(self):
        with mock.patch.object(llama, "_template", return_value="{% if enable_thinking %}<think>{% endif %}"), \
                mock.patch.object(llama, "model_files", return_value={"q": (Path("q.gguf"), None)}):
            self.assertEqual(llama.thinking_modes("q"), ([True, False], True))

    def test_claude_generations(self):
        self.assertEqual(integrations.thinking_modes("anthropic:claude-opus-5-5")[0][0], "low")
        self.assertIn(False, integrations.thinking_modes("anthropic:claude-sonnet-5-5")[0])
        self.assertEqual(integrations._claude_thinking("claude-haiku-4-5")[2], "budget")
        self.assertEqual(integrations.thinking_modes("anthropic:claude-3-5-haiku-20241022"), ([], None))


class GeneratedFilesAreMarked(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def picture(self, name):
        from PIL import Image
        path = self.folder / name
        Image.new("RGB", (8, 8), "red").save(path)
        self.assertTrue(ai_mark.mark_file(path))
        return path

    def test_pictures_stay_readable_and_carry_the_mark(self):
        from PIL import Image
        for name, field in (("a.png", "XML:com.adobe.xmp"), ("a.jpg", "xmp")):
            path = self.picture(name)
            self.assertIn(b"trainedAlgorithmicMedia", path.read_bytes())
            with Image.open(path) as image:
                image.load()
                self.assertIn("trainedAlgorithmicMedia", str(image.info[field]))
            self.assertFalse(path.with_name(name + ".xmp").exists())

    def box(self, kind, body=b""):
        return (8 + len(body)).to_bytes(4, "big") + kind + body

    def test_a_video_gets_the_mark_as_a_last_box(self):
        path = self.folder / "a.mp4"
        original = self.box(b"ftyp", b"isom") + self.box(b"mdat", b"x" * 20) + self.box(b"moov", b"y")
        path.write_bytes(original)
        self.assertTrue(ai_mark.mark_file(path))
        data = path.read_bytes()
        self.assertTrue(data.startswith(original))
        self.assertEqual(data[len(original) + 4:len(original) + 8], b"uuid")
        self.assertEqual(int.from_bytes(data[len(original):len(original) + 4], "big"), len(data) - len(original))

    def test_a_video_that_cannot_take_a_box_is_marked_beside_it(self):
        path = self.folder / "a.mp4"
        original = self.box(b"ftyp", b"isom") + (0).to_bytes(4, "big") + b"mdat" + b"x" * 20
        path.write_bytes(original)
        self.assertTrue(ai_mark.mark_file(path))
        self.assertEqual(path.read_bytes(), original)
        self.assertIn(b"trainedAlgorithmicMedia", (self.folder / "a.mp4.xmp").read_bytes())

    def test_a_broken_or_unknown_file_is_left_alone(self):
        for name in ("a.png", "a.webm"):
            path = self.folder / name
            path.write_bytes(b"not really")
            self.assertTrue(ai_mark.mark_file(path))
            self.assertEqual(path.read_bytes(), b"not really")
            self.assertTrue(path.with_name(name + ".xmp").exists())


class PairedPhones(unittest.TestCase):
    def setUp(self):
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader("main_window_phones", str(ROOT / "app" / "window" / "main.pyw"))
        spec = importlib.util.spec_from_loader("main_window_phones", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        self.app = types.SimpleNamespace(settings={}, _state_lock=threading.Lock(), _save_settings=lambda: None)
        self.api = module.WebApi.__new__(module.WebApi)
        self.api._app = self.app
        sealed = mock.patch.object(integrations, "seal", lambda text: "sealed:" + text)
        opened = mock.patch.object(integrations, "unseal", lambda text: text[7:] if text.startswith("sealed:") else "")
        sealed.start(); opened.start()
        self.addCleanup(sealed.stop); self.addCleanup(opened.stop)

    def test_a_phone_is_kept_with_its_secret_sealed(self):
        secret = "s" * 43
        self.assertTrue(self.api.remote_add("phone12345", secret, "iPhone")["ok"])
        stored = self.app.settings["remote_devices"][0]
        self.assertNotEqual(stored["secret"], secret)
        self.assertEqual(self.api.remote_secrets(), [{"id": "phone12345", "secret": secret}])
        self.assertEqual(self.api.remote_devices()[0]["name"], "iPhone")
        self.assertNotIn("secret", self.api.remote_devices()[0])

    def test_bad_pairing_data_is_refused(self):
        self.assertFalse(self.api.remote_add("x", "s" * 43)["ok"])
        self.assertFalse(self.api.remote_add("phone12345", "short")["ok"])
        self.assertFalse(self.api.remote_add("../../evil", "s" * 43)["ok"])
        self.assertEqual(self.app.settings.get("remote_devices", []), [])

    def test_a_phone_can_be_seen_renamed_and_forgotten(self):
        self.api.remote_add("phone12345", "s" * 43)
        self.assertTrue(self.api.remote_update("phone12345", "Мой iPhone", True)["ok"])
        device = self.api.remote_devices()[0]
        self.assertEqual(device["name"], "Мой iPhone")
        self.assertGreater(device["seen"], 0)
        self.api.remote_forget("phone12345")
        self.assertEqual(self.api.remote_devices(), [])
        self.assertEqual(self.api.remote_secrets(), [])


class Updates(unittest.TestCase):
    def setUp(self):
        from app import update
        self.update = update
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name)

    def release(self, tag, assets=None, **extra):
        return io.BytesIO(json.dumps({"tag_name": tag, "name": tag, "body": "notes", "html_url": "https://github.com/x", "assets": assets or [], **extra}).encode())

    def test_versions_compare_as_numbers(self):
        self.assertTrue(self.update.is_newer("0.10.0", "0.9.9"))
        self.assertTrue(self.update.is_newer("v0.2.0", "0.1.0"))
        self.assertFalse(self.update.is_newer("0.1.0", "0.1.0"))
        self.assertFalse(self.update.is_newer("", "0.1.0"))
        self.assertFalse(self.update.is_newer("PIVEN-Companion-0.1.0-Setup", "0.1.0"))
        self.assertTrue(self.update.is_newer("PIVEN-Companion-0.2.0-Setup", "0.1.0"))

    def test_the_installer_and_its_checksum_are_found(self):
        assets = [{"name": "notes.txt"}, {"name": "PIVEN-Companion-0.2.0-Setup.exe", "size": 5, "browser_download_url": "https://github.com/a.exe", "digest": "sha256:ABC"}]
        with mock.patch.object(self.update.urllib.request, "urlopen", return_value=self.release("v0.2.0", assets)):
            latest = self.update.latest_release()
        self.assertEqual(latest["version"], "0.2.0")
        self.assertEqual(latest["installer"]["sha256"], "abc")

    def test_drafts_and_previews_are_ignored(self):
        with mock.patch.object(self.update.urllib.request, "urlopen", return_value=self.release("v9.0.0", prerelease=True)):
            self.assertIsNone(self.update.latest_release())

    def test_a_copy_run_from_sources_downloads_the_installer_too(self):
        updater = self.update.Updater(self.folder, self.folder)
        updater.latest = {"version": "9.0.0", "notes": "x" * 20000, "installer": {"name": "a-Setup.exe", "size": 1, "url": "https://evil.example/a", "sha256": ""}}
        status = updater.status()
        self.assertTrue(status["canInstall"])
        self.assertTrue(status["fromSources"])
        self.assertEqual(len(status["notes"]), 20000)
        self.assertIn("GitHub", updater.download()["error"], "the link check still applies")

    def test_only_github_links_are_downloaded(self):
        (self.folder / "unins000.exe").write_bytes(b"")
        updater = self.update.Updater(self.folder, self.folder)
        updater.latest = {"version": "9.0.0", "installer": {"name": "a-Setup.exe", "size": 1, "url": "https://evil.example/a.exe", "sha256": ""}}
        self.assertIn("GitHub", updater.download()["error"])

    def test_a_download_that_does_not_match_its_checksum_is_thrown_away(self):
        (self.folder / "unins000.exe").write_bytes(b"")
        data = b"installer bytes"
        updater = self.update.Updater(self.folder, self.folder)
        for checksum, expected in (("0" * 64, "error"), (hashlib.sha256(data).hexdigest(), "done")):
            updater.latest = {"version": "9.0.0", "installer": {"name": "PIVEN-Companion-9.0.0-Setup.exe", "size": len(data), "url": "https://github.com/a.exe", "sha256": checksum}}
            with mock.patch.object(self.update.download, "fetch", side_effect=lambda url, partial, **kw: partial.write_bytes(data)):
                self.assertTrue(updater.download()["ok"])
                for _ in range(100):
                    if updater.job["state"] != "running":
                        break
                    time.sleep(0.02)
            self.assertEqual(updater.job["state"], expected)
            self.assertEqual(bool(updater.ready), expected == "done")

    def test_old_installers_are_cleaned_but_a_waiting_newer_one_is_kept(self):
        folder = self.folder / "updates"
        folder.mkdir()
        (folder / "PIVEN-Companion-0.1.0-Setup.exe").write_bytes(b"x")
        (folder / "PIVEN-Companion-9.0.0-Setup.exe").write_bytes(b"x")
        self.update.Updater(self.folder, self.folder).clean()
        self.assertEqual([item.name for item in folder.iterdir()], ["PIVEN-Companion-9.0.0-Setup.exe"])

    def test_the_installer_version_matches_the_program(self):
        script = (ROOT / "installer" / "piven.iss").read_text(encoding="utf-8-sig")
        self.assertIn(f'#define AppVersion "{self.update.VERSION}"', script)


class NativeTexts(unittest.TestCase):
    def test_texts_outside_the_window_follow_the_language(self):
        from app import i18n
        self.assertEqual(i18n.translate("Открыть PIVEN", "en"), "Open PIVEN")
        self.assertEqual(i18n.translate("Открыть PIVEN", "ru"), "Открыть PIVEN")
        self.assertEqual(i18n.translate("Ответ в чате «Рецепт»", "en"), "Reply in chat «Рецепт»")
        self.assertEqual(i18n.translate("Можно выполнить команду? pip install x", "en"), "May I run a command? pip install x")
        self.assertEqual(i18n.translate("Some English text", "en"), "Some English text")
        self.assertEqual(i18n.translate("Совсем неизвестная фраза", "en"), "Совсем неизвестная фраза")


class ModelDeletion(unittest.TestCase):
    def test_deletes_when_windows_redirects_the_data_folder(self):
        from app import paths
        with tempfile.TemporaryDirectory() as folder:
            models = Path(folder) / "models"
            (models / "repo").mkdir(parents=True)
            weights = models / "repo" / "tiny.gguf"
            weights.write_bytes(b"0" * 64)
            redirected = lambda self, strict=False: Path(folder) / "Packages" / "LocalCache" / self.name
            with mock.patch.object(llama, "MODELS_DIR", models), mock.patch.object(llama, "HF_MODELS_DIR", Path(folder) / "hf"), \
                    mock.patch.object(llama, "MIN_MODEL_BYTES", 1), mock.patch.object(llama, "stop_model"), \
                    mock.patch.object(Path, "resolve", redirected):
                self.assertEqual(llama.delete_model("tiny"), 64)
            self.assertFalse(weights.exists())
            self.assertFalse((models / "repo").exists())
            self.assertTrue(models.exists())
        root = r"C:\Users\x\AppData\Local\PIVEN\models"
        self.assertTrue(paths.inside(r"C:\Users\x\AppData\Local\piven\Models\a\b.gguf", [root]))
        self.assertFalse(paths.inside(r"C:\Users\x\AppData\Local\PIVEN\models-old\b.gguf", [root]))
        self.assertFalse(paths.inside(r"C:\Users\x\AppData\Local\PIVEN\models\..\settings.json", [root]))
        self.assertFalse(paths.inside(root, [root]))


class MemorySavings(unittest.TestCase):
    def test_server_keeps_fewer_context_copies_and_a_smaller_prompt_cache(self):
        gb = 2 ** 30
        for ram, expected in ((32 * gb, 4096), (8 * gb, 2048), (128 * gb, 8192), (0, 8192)):
            with mock.patch("app.models.memory_fit.system_ram", return_value=ram):
                self.assertEqual(llama.prompt_cache_mb(), expected)
        with mock.patch("app.models.memory_fit.system_ram", return_value=32 * gb), mock.patch("app.models.memory_fit.gpu_memory", return_value=0):
            options = llama._server_options("m", llama.params_for("m"), None)
        self.assertEqual(options[options.index("-ctxcp") + 1], "8")
        self.assertEqual(options[options.index("-cram") + 1], "4096")

    def test_idle_voice_is_unloaded_only_outside_calls_and_dictation(self):
        class Process:
            def __init__(self):
                self.stopped = False
            def poll(self):
                return 0 if self.stopped else None
            def terminate(self):
                self.stopped = True
            def wait(self, timeout=None):
                return 0

        def make():
            companion = object.__new__(core.CompanionCore)
            companion.tts_lock, companion.asr_lock = threading.Lock(), threading.Lock()
            companion.tts_process, companion.asr_process = Process(), Process()
            companion.running, companion.dictation, companion.voice_used_at = False, {"phase": ""}, 0.0
            return companion

        companion = make()
        self.assertFalse(companion._release_idle_voice(now=core.VOICE_IDLE_SECONDS - 1))
        companion.running = True
        self.assertFalse(companion._release_idle_voice(now=core.VOICE_IDLE_SECONDS + 1))
        companion.running, companion.dictation = False, {"phase": "listening"}
        self.assertFalse(companion._release_idle_voice(now=core.VOICE_IDLE_SECONDS + 1))
        companion.dictation = {"phase": ""}
        with companion.tts_lock:
            tts = companion.tts_process
            self.assertTrue(companion._release_idle_voice(now=core.VOICE_IDLE_SECONDS + 1))
        self.assertIs(companion.tts_process, tts, "speech in progress keeps its server")
        self.assertIsNone(companion.asr_process)
        self.assertTrue(companion._release_idle_voice(now=core.VOICE_IDLE_SECONDS + 1))
        self.assertTrue(tts.stopped)
        self.assertIsNone(companion.tts_process)
        self.assertFalse(companion._release_idle_voice(now=core.VOICE_IDLE_SECONDS + 1))

    def test_driver_cache_is_big_enough_for_child_processes(self):
        self.assertGreaterEqual(int(core.os.environ["CUDA_CACHE_MAXSIZE"]), 2 ** 30)


class PolishFixes(unittest.TestCase):
    def test_gemini_thought_signature_goes_back_with_the_tool_call(self):
        calls = {}
        llama.collect_tool_calls({"tool_calls": [{"index": 0, "id": "a", "function": {"name": "list_files", "arguments": "{}"},
                                                  "extra_content": {"google": {"thought_signature": "sig"}}}]}, calls)
        finished = llama.finished_tool_calls(calls)
        self.assertEqual(finished[0]["extra"], {"google": {"thought_signature": "sig"}})
        wire = llama._to_openai([{"role": "assistant", "content": "", "tool_calls": finished}])
        self.assertEqual(wire[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"], "sig")
        plain = llama._to_openai([{"role": "assistant", "content": "", "tool_calls": [{"id": "b", "name": "x", "arguments": {}}]}])
        self.assertNotIn("extra_content", plain[0]["tool_calls"][0])

    def test_thinking_brake_waits_like_the_cancel_event(self):
        from app.chat.coding import ThinkingBrake
        cancel = threading.Event()
        brake = ThinkingBrake(cancel, 16384, True)
        self.assertFalse(brake.wait(0.01))
        cancel.set()
        self.assertTrue(brake.wait(0.01))

    def test_model_icon_comes_from_the_hugging_face_repo(self):
        from app.models import logos
        with mock.patch.object(logos, "_base_model", return_value="DavidAU/Some-Finetune"):
            self.assertEqual(logos.repo_owner("mradermacher/Some-Finetune-GGUF"), "DavidAU")
        self.assertEqual(logos.repo_owner("DavidAU/Own-GGUF"), "DavidAU")
        with mock.patch.object(logos, "_base_model", return_value=None):
            self.assertEqual(logos.repo_owner("bartowski/X-GGUF"), "", "a failed lookup is asked again later")
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(logos, "CACHE_PATH", Path(folder) / "logos.json"), \
                mock.patch.object(logos, "_cache", {"DavidAU": "https://a/david.png", "Qwen": "https://a/qwen.png"}), \
                mock.patch.object(logos, "repo_owner", return_value="DavidAU"):
            found = logos.logos(["Qwen3.5-9B-Finetune"], {}, {"Qwen3.5-9B-Finetune": "qwen35"}, {"Qwen3.5-9B-Finetune": "mradermacher/Qwen3.5-9B-Finetune-GGUF"})
            self.assertEqual(found["Qwen3.5-9B-Finetune"], "https://a/david.png")
            self.assertEqual(logos.logos(["qwen-other"], {}, {"qwen-other": "qwen35"})["qwen-other"], "https://a/qwen.png")

    def test_llama_switch_leaves_connected_services_and_comfyui_always_on(self):
        self.assertEqual(core.CompanionCore._load_integrations({"models": False, "comfyui": False}), {"models": False, "comfyui": True})
        companion = object.__new__(core.CompanionCore)
        companion.settings = {"integrations_enabled": {"models": False}}
        with mock.patch.object(core.integrations, "is_provider_model", side_effect=lambda name: name.startswith("gemini:")):
            self.assertTrue(companion._local_blocked("Qwen3.5-9B"))
            self.assertFalse(companion._local_blocked("gemini:gemini-2.5-flash"))
        companion.settings = {"integrations_enabled": {"models": True}}
        self.assertFalse(companion._local_blocked("Qwen3.5-9B"))

    def test_update_rate_limit_is_explained(self):
        from app import update
        updater = update.Updater(ROOT, tempfile.gettempdir())
        error = urllib.error.HTTPError(update.LATEST, 403, "rate limit exceeded", {}, None)
        with mock.patch.object(update, "latest_release", side_effect=error):
            updater.check()
        self.assertIn("временно ограничил", updater.error)


class CloudModels(unittest.TestCase):
    def http_error(self, code, body, headers=None):
        return urllib.error.HTTPError("https://x", code, "error", headers or {}, io.BytesIO(body.encode("utf-8")))

    def test_rate_limits_are_told_apart(self):
        minute = '{"error": {"message": "Quota exceeded for metric: generate_content_free_tier_requests, limit: 5", "details": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}, {"retryDelay": "37s"}]}}'
        day = '{"error": {"message": "Quota exceeded", "details": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}'
        self.assertEqual(integrations.retry_delay(self.http_error(429, minute), minute), 37.0)
        self.assertEqual(integrations.retry_delay(self.http_error(429, "{}", {"Retry-After": "12"}), "{}"), 12.0)
        self.assertIsNone(integrations.retry_delay(self.http_error(429, day), day))
        self.assertIn("подожди минуту", integrations._http_error(self.http_error(429, minute)))
        self.assertIn("дневной лимит", integrations._http_error(self.http_error(429, day)))
        self.assertIn("закончились деньги", integrations._http_error(self.http_error(429, '{"error": {"message": "insufficient credits"}}')))

    def test_chat_waits_when_the_service_asks_and_retries_a_dropped_stream(self):
        statuses, waits = [], []

        class Cancel:
            def wait(self, seconds):
                waits.append(seconds)
                return False

            def is_set(self):
                return False

        replies = [integrations._Busy("Google Gemini: слишком много запросов", 37.0), integrations._Lost("Google Gemini: сервер оборвал ответ"), "готово"]

        def ask(*args, **kwargs):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        with mock.patch.object(integrations, "_ask", side_effect=ask):
            self.assertEqual(integrations.chat("gemini:gemini-2.5-flash", [], on_status=statuses.append, cancel_event=Cancel()), "готово")
        self.assertEqual(waits, [38.0, integrations.RETRY_WAITS[0]])
        self.assertIn("Google Gemini просит подождать 37 с", statuses)

        replies[:] = [integrations._Busy("x", 5.0)] * 5
        with mock.patch.object(integrations, "_ask", side_effect=ask):
            with self.assertRaises(RuntimeError):
                integrations.chat("gemini:gemini-2.5-flash", [], cancel_event=Cancel())

    def test_stream_closed_by_the_server_counts_as_a_lost_connection(self):
        class Dropped:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def __iter__(self):
                raise AttributeError("'NoneType' object has no attribute 'peek'")

        with mock.patch.object(integrations, "settings_of", return_value={"url": "http://127.0.0.1:1/v1", "key": ""}), \
                mock.patch.object(integrations, "_open_stream", return_value=Dropped()):
            with self.assertRaises(integrations._Lost) as caught:
                integrations._ask("openrouter:some/model", [{"role": "user", "content": "hi"}])
        self.assertIn("сервер оборвал ответ", str(caught.exception))


class FakeStream(io.BytesIO):
    pass


class VllmProvider(unittest.TestCase):
    def test_vllm_appears_in_settings_without_a_windows_install(self):
        with mock.patch.dict(integrations.config, clear=True):
            row = next(row for row in integrations.status() if row["id"] == "vllm")
        self.assertTrue(row["installed"])
        self.assertFalse(row["enabled"])
        self.assertEqual(row["url"], "http://127.0.0.1:8000/v1")

    def test_discovers_models_and_streams_chat_through_the_configured_server(self):
        model = "Qwen/chat:alias"
        received = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                received.append((self.path, self.headers.get("Authorization"), None))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"data": [{"id": model}]}).encode())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, self.headers.get("Authorization"), body))
                if "tools" in body:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error":{"message":"Auto tool choice requires --enable-auto-tool-choice"}}')
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\ndata: [DONE]\n\n')

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            config = {"vllm": {"enabled": True, "url": f"http://127.0.0.1:{server.server_port}/proxy/", "key": "sealed"}}
            try:
                with mock.patch.dict(integrations.config, config, clear=True), \
                        mock.patch.object(integrations, "unseal", return_value="token"):
                    discovered = integrations.fetch_models("vllm")
                    name = f"vllm:{discovered[0]}"
                    answer = llama.chat(name, [{"role": "user", "content": "hi"}], timeout=3,
                                        tools=[{"type": "function", "function": {"name": "example"}}])
            finally:
                server.shutdown()
                worker.join()
        self.assertEqual(discovered, [model])
        self.assertEqual(answer, "hello")
        self.assertEqual([path for path, _, _ in received], [
            "/proxy/v1/models", "/proxy/v1/chat/completions", "/proxy/v1/chat/completions",
        ])
        self.assertTrue(all(auth == "Bearer token" for _, auth, _ in received))
        first, second = received[1][2], received[2][2]
        self.assertIn("tools", first)
        self.assertNotIn("tools", second)
        self.assertEqual(second["model"], model)
        self.assertTrue(second["stream"])
        self.assertIn("repetition_penalty", second)
        self.assertNotIn("repeat_penalty", second)


class LocalChatServers(unittest.TestCase):
    def test_strata_and_unsloth_start_disabled_with_local_defaults(self):
        with mock.patch.dict(integrations.config, clear=True):
            rows = {row["id"]: row for row in integrations.status()}
        for provider, port in (("strata", 8080), ("unsloth", 8888)):
            with self.subTest(provider=provider):
                row = rows[provider]
                self.assertTrue(row["local"] and row["needsKey"])
                self.assertFalse(row["enabled"])
                self.assertEqual(row["url"], f"http://127.0.0.1:{port}/v1")
                self.assertTrue(row["site"])

    def test_discovers_models_and_streams_chat_with_provider_options(self):
        strata_model = "local-model"
        unsloth_model = "unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_XL"
        received = []
        tools = [{"type": "function", "function": {"name": "example"}}]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                auth = self.headers.get("Authorization")
                received.append((self.path, auth, None))
                if self.path.startswith("/studio/") and auth != "Bearer sk-unsloth-test":
                    self.send_error(401)
                    return
                models = [{"id": strata_model}] if self.path.startswith("/strata/") else [
                    {"id": unsloth_model, "loaded": True},
                    {"id": "on-disk", "loaded": False},
                    {"id": "image-model", "loaded": True, "task": "text-to-image"},
                ]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"data": models}).encode())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, self.headers.get("Authorization"), body))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                if body.get("reasoning_effort") == "medium":
                    self.wfile.write(b'data: {"choices":[{"delta":{"reasoning_content":"thinking"}}]}\n\n')
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\ndata: [DONE]\n')

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            config = {
                "strata": {"enabled": True, "url": base + "/strata/"},
                "unsloth": {"enabled": True, "url": base + "/studio/v1/", "key": "sealed"},
            }
            try:
                with mock.patch.dict(integrations.config, config, clear=True), \
                        mock.patch.object(integrations, "unseal", side_effect=lambda key: "sk-unsloth-test" if key else ""), \
                        mock.patch.dict(integrations._models, clear=True), \
                        mock.patch.dict(llama.model_params, {f"unsloth:{unsloth_model}": {
                            "top_k": 500, "repeat_penalty": 3.0, "temperature": 4.0,
                        }}, clear=True):
                    with self.assertRaises(integrations.KeyRejected):
                        integrations.fetch_models("unsloth", key="")
                    for provider, model, think in (("strata", strata_model, "medium"), ("unsloth", unsloth_model, False)):
                        with self.subTest(provider=provider):
                            self.assertTrue(integrations.refresh_one(provider))
                            name = f"{provider}:{model}"
                            self.assertIn(name, integrations.model_names())
                            thoughts = []
                            answer = llama.chat(name, [{"role": "user", "content": "hi"}], think=think,
                                                timeout=3, on_thinking=thoughts.append, tools=tools)
                            self.assertEqual(answer, "hello")
                            self.assertEqual(thoughts[-1:], ["thinking"] if provider == "strata" else [])
                    self.assertCountEqual(integrations.model_names(), [f"strata:{strata_model}", f"unsloth:{unsloth_model}"])
            finally:
                server.shutdown()
                worker.join()
        self.assertEqual([(path, key) for path, key, _ in received], [
            ("/studio/v1/models", None),
            ("/strata/v1/models", None), ("/strata/v1/chat/completions", None),
            ("/studio/v1/models", "Bearer sk-unsloth-test"), ("/studio/v1/chat/completions", "Bearer sk-unsloth-test"),
        ])
        strata, unsloth = received[2][2], received[4][2]
        self.assertTrue(strata["stream"] and unsloth["stream"])
        self.assertEqual(strata["tools"], tools)
        self.assertEqual(unsloth["tools"], tools)
        self.assertEqual(strata["model"], strata_model)
        self.assertEqual(strata["reasoning_effort"], "medium")
        self.assertEqual(unsloth["model"], unsloth_model)
        self.assertIs(unsloth["enable_thinking"], False)
        self.assertIs(unsloth["enable_tools"], False)
        self.assertEqual((unsloth["top_k"], unsloth["repetition_penalty"], unsloth["temperature"]), (100, 2.0, 2.0))


class ProviderConnection(unittest.TestCase):
    def setUp(self):
        for store in (integrations._models, integrations._errors, integrations._kinds, integrations._next_try, integrations._gaps):
            patcher = mock.patch.dict(store, clear=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(integrations, "settings_of", lambda p: {"enabled": True, "url": "http://x", "key": "k"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def refused(self, code):
        return urllib.error.HTTPError("http://x", code, "no", {}, io.BytesIO(b"{}"))

    def test_pasted_keys_are_cleaned(self):
        clean = integrations.clean_key
        self.assertEqual(clean("  sk-abc\r\n"), "sk-abc")
        self.assertEqual(clean('"sk-abc"'), "sk-abc")
        self.assertEqual(clean("Bearer sk-abc"), "sk-abc")
        self.assertEqual(clean("Authorization: Bearer sk-abc"), "sk-abc")
        self.assertEqual(clean("OPENAI_API_KEY=sk-abc"), "sk-abc")
        self.assertEqual(clean("\ufeffsk-abc\u200b"), "sk-abc")
        self.assertEqual(clean("   "), "")

    def test_a_refused_key_is_reported_and_not_retried(self):
        with mock.patch.object(integrations, "_get", side_effect=self.refused(401)) as get:
            self.assertFalse(integrations.refresh_one("openai"))
            self.assertEqual(integrations._kinds["openai"], "key")
            self.assertFalse(integrations.retry_lost())
        self.assertEqual(get.call_count, 1)

    def test_a_lost_connection_keeps_the_models_and_comes_back(self):
        integrations._models["openai"] = ["gpt-5"]
        with mock.patch.object(integrations, "_get", side_effect=OSError("down")):
            self.assertFalse(integrations.refresh_one("openai"))
        self.assertEqual(integrations._models["openai"], ["gpt-5"])
        self.assertEqual(integrations._kinds["openai"], "lost")
        with mock.patch.object(integrations, "_get", return_value={"data": [{"id": "gpt-6"}]}):
            self.assertTrue(integrations.retry_lost())
        self.assertEqual(integrations._models["openai"], ["gpt-6"])
        self.assertNotIn("openai", integrations._errors)

    def test_retries_wait_longer_each_time(self):
        with mock.patch.object(integrations, "_get", side_effect=OSError("down")) as get:
            integrations.refresh_one("openai")
            integrations.retry_lost()
            first = integrations._gaps["openai"]
            integrations.retry_lost()
            self.assertEqual(get.call_count, 2)
            integrations._next_try["openai"] = 0
            integrations.retry_lost()
        self.assertEqual(first, integrations.RECONNECT_FIRST)
        self.assertEqual(integrations._gaps["openai"], first * 2)

    def test_a_bad_key_is_told_apart_from_no_connection(self):
        with mock.patch.object(integrations, "_get", side_effect=self.refused(401)):
            self.assertIn("401", integrations.try_key("openai", "bad"))
        with mock.patch.object(integrations, "_get", side_effect=OSError("down")):
            self.assertEqual(integrations.try_key("openai", "maybe"), "")

    def test_the_answer_survives_a_dropped_connection(self):
        answer = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n'
        statuses = []
        with mock.patch.object(integrations, "RETRY_WAITS", (0,)), \
                mock.patch.object(integrations.urllib.request, "urlopen", side_effect=[urllib.error.URLError("down"), FakeStream(answer)]):
            self.assertEqual(integrations.chat("openai:gpt-5", [{"role": "user", "content": "x"}], on_status=statuses.append), "hi")
        self.assertIn("Связь оборвалась, подключаюсь снова", statuses)

    def test_a_started_answer_is_not_sent_twice(self):
        class Breaks:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"hi"}}]}'
                raise ConnectionResetError("cut")
        with mock.patch.object(integrations, "RETRY_WAITS", (0,)), \
                mock.patch.object(integrations.urllib.request, "urlopen", return_value=Breaks()) as opened:
            with self.assertRaises(RuntimeError):
                integrations.chat("openai:gpt-5", [{"role": "user", "content": "x"}])
        self.assertEqual(opened.call_count, 1)

    def test_a_refused_request_is_not_repeated(self):
        with mock.patch.object(integrations, "RETRY_WAITS", (0,)), \
                mock.patch.object(integrations.urllib.request, "urlopen", side_effect=self.refused(401)) as opened:
            with self.assertRaises(RuntimeError):
                integrations.chat("openai:gpt-5", [{"role": "user", "content": "x"}])
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(integrations._kinds["openai"], "key")


class ProviderRequests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(integrations, "RETRY_WAITS", ())
        patcher.start()
        self.addCleanup(patcher.stop)

    def body(self, name, think):
        sent = []

        def capture(request, timeout=0):
            sent.append(json.loads(request.data))
            raise OSError("captured")
        with mock.patch.object(integrations.urllib.request, "urlopen", capture), \
                mock.patch.object(integrations, "settings_of", lambda p: {"enabled": True, "url": integrations.PROVIDERS[p]["url"], "key": "k"}):
            try:
                integrations.chat(name, [{"role": "user", "content": "hi"}], sampling={"temperature": 0.7}, think=think)
            except Exception:
                pass
        return sent[-1]

    def test_claude_effort_and_no_temperature_on_new_models(self):
        body = self.body("anthropic:claude-opus-5-5", "high")
        self.assertEqual(body["output_config"], {"effort": "high"})
        self.assertNotIn("temperature", body)
        self.assertEqual(self.body("anthropic:claude-sonnet-5-5", False)["thinking"], {"type": "between_tools"})

    def test_claude_streams_native_tool_calls_and_receives_their_results(self):
        payloads = []
        events = [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Read the entrypoint."}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "opaque"}},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {}}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"path":'}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '"src/main.py"}'}},
        ]

        def stream(_url, payload, *_):
            payloads.append(payload)
            chunks = events if len(payloads) == 1 else [{"delta": {"type": "text_delta", "text": "Done."}}]
            return FakeStream("".join(f"data: {json.dumps(event)}\n\n" for event in chunks).encode())

        specs = [{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}]
        messages = [{"role": "user", "content": "Find the entrypoint"}]
        calls = []
        with mock.patch.object(integrations, "_open_stream", side_effect=stream):
            integrations.chat("anthropic:claude-sonnet-4-5", messages, tools=specs, tool_calls=calls)
            self.assertEqual(calls[0]["arguments"], {"path": "src/main.py"})
            messages.extend([{"role": "assistant", "content": "", "tool_calls": calls},
                             {"role": "tool", "tool_call_id": "toolu_1", "content": "print('hi')"}])
            self.assertEqual(integrations.chat("anthropic:claude-sonnet-4-5", messages, tools=specs, overrides={"tool_choice": "none"}), "Done.")
        self.assertEqual(payloads[0]["tools"][0]["input_schema"], {"type": "object"})
        self.assertEqual(payloads[1]["tool_choice"], {"type": "none"})
        self.assertEqual(payloads[1]["messages"][1]["content"], [
            {"type": "thinking", "thinking": "Read the entrypoint.", "signature": "opaque"},
            {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "src/main.py"}},
        ])
        self.assertEqual(payloads[1]["messages"][2]["content"], [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "print('hi')"},
        ])

    def test_old_claude_keeps_temperature_and_gets_a_budget(self):
        self.assertEqual(self.body("anthropic:claude-3-5-haiku-20241022", "__auto__")["temperature"], 0.7)
        body = self.body("anthropic:claude-haiku-4-5", "medium")
        self.assertEqual(body["thinking"]["budget_tokens"], 8192)
        self.assertGreater(body["max_tokens"], 8192)

    def test_openai_reasoning_model(self):
        body = self.body("openai:gpt-5.1", "low")
        self.assertEqual(body["reasoning_effort"], "low")
        self.assertNotIn("temperature", body)
        self.assertEqual(self.body("openai:gpt-5.1", False)["reasoning_effort"], "none")

    def test_cloud_levels_follow_the_model(self):
        modes = integrations.thinking_modes
        self.assertEqual(modes("openai:o3-mini")[0], ["low", "medium", "high"])
        self.assertEqual(modes("openai:gpt-5")[0], ["minimal", "low", "medium", "high"])
        self.assertEqual(modes("openai:gpt-5.2")[0], [False, "low", "medium", "high", "xhigh"])
        self.assertEqual(modes("openai:gpt-4o"), ([], None))
        self.assertEqual(modes("gemini:gemini-2.5-flash")[0], [False, "low", "medium", "high"])
        self.assertEqual(modes("gemini:gemini-3-pro")[0], ["low", "high"])
        self.assertEqual(modes("gemini:gemini-4-argon"), (["low", "medium", "high"], "medium"))
        self.assertEqual(modes("gemini:gemini-3.1-pro-preview"), (["low", "medium", "high"], "high"))
        self.assertEqual(modes("gemini:gemini-nano-banana-2.1"), ([], None))
        self.assertEqual(modes("gemini:gemini-1.5-pro"), ([], None))

    def test_refusals_tell_the_real_levels(self):
        read = integrations.levels_from_error
        known = [False, "low", "medium", "high", "xhigh"]
        self.assertEqual(read("Invalid value. Valid values are: high, low, medium, none", known), [False, "low", "medium", "high"])
        self.assertEqual(read("Unsupported value: 'xhigh' is not supported. Supported values are: 'low', 'medium', and 'high'.", known), ["low", "medium", "high"])
        self.assertEqual(read("Supported types are xhigh (default), medium, and low.", known), ["low", "medium", "xhigh"])
        self.assertEqual(read("Thinking level MEDIUM is not supported for this model.", known), [False, "low", "high", "xhigh"])
        self.assertEqual(read("Unsupported value: 'none'", known), ["low", "medium", "high", "xhigh"])

    def test_unrelated_refusals_teach_nothing(self):
        read = integrations.levels_from_error
        known = ["low", "high"]
        self.assertIsNone(read("Valid values are: user, assistant, system", known))
        self.assertIsNone(read("The message is too long.", known))
        self.assertIsNone(read("max_tokens is invalid", known))

    def test_learned_levels_replace_the_guess_and_are_saved(self):
        saved = []
        name = "gemini:gemini-9-test"

        def refuse_then_answer(request, timeout=None):
            if "reasoning_effort" in json.loads(request.data.decode("utf-8")):
                raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, io.BytesIO(b'{"error":{"message":"Valid values are: low, high"}}'))
            return "stream"
        with mock.patch.dict(integrations.learned, clear=True), mock.patch.object(integrations, "on_learned", lambda model, values: saved.append((model, values))), \
                mock.patch.object(integrations.urllib.request, "urlopen", refuse_then_answer):
            self.assertEqual(integrations._open_stream("http://x", {"reasoning_effort": "medium"}, {}, 5, name, "medium"), "stream")
            self.assertEqual(saved, [(name, ["low", "high"])])
            self.assertEqual(integrations.thinking_modes(name)[0], ["low", "high"])
            payload = {}
            integrations._apply_thinking("gemini", "gemini-9-test", payload, "medium")
            self.assertEqual(payload, {})

    def test_remembering_levels_drops_a_choice_that_no_longer_exists(self):
        state = fake_core(_save_settings=lambda: None)
        state.settings.update(thinking_levels={"m": "medium"}, thinking_capabilities={"m": {}})
        with mock.patch.dict(core.THINKING_LEVELS, {"m": "medium"}):
            Core._remember_levels(state, "m", ["low", "high"])
            self.assertNotIn("m", core.THINKING_LEVELS)
        self.assertEqual(state.settings["thinking_levels"], {})
        self.assertEqual(state.settings["thinking_capabilities"], {})
        self.assertEqual(state.settings["thinking_learned"], {"m": ["low", "high"]})

    def test_models_that_do_not_exist_yet_still_get_levels(self):
        modes = integrations.thinking_modes
        for name in ("gemini:gemini-5-carbon", "gemini:gemini-carbon", "openai:gpt-6", "openai:o5-mini"):
            self.assertIn("medium", modes(name)[0], name)
        self.assertIn("high", modes("anthropic:claude-newname-6")[0])
        self.assertEqual(modes("openai:gpt-4o"), ([], None))
        self.assertEqual(modes("openai:gpt-3.5-turbo"), ([], None))
        self.assertEqual(modes("anthropic:claude-instant-1-2"), ([], None))
        self.assertEqual(modes("custom:my-model"), ([True, False], True))

    def test_openrouter_uses_what_the_service_reports(self):
        read = integrations._openrouter_thinking
        self.assertEqual(read({"reasoning": {"mandatory": True, "supported_efforts": ["max", "high", "low"], "default_effort": "max"}}), (["low", "high", "max"], "max"))
        self.assertEqual(read({"reasoning": {"mandatory": False, "supported_efforts": ["high", "low"]}})[0], [False, "low", "high"])
        self.assertEqual(read({"reasoning": {"mandatory": False, "default_enabled": False}}), ([True, False], False))
        self.assertEqual(read({"reasoning": {"mandatory": True}}), ([], True))

    def test_rejected_level_still_gets_an_answer(self):
        sent = []

        def fake(request, timeout=None):
            sent.append(json.loads(request.data.decode("utf-8")))
            if "reasoning_effort" in sent[-1]:
                raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, None)
            return "stream"
        with mock.patch.object(integrations.urllib.request, "urlopen", fake):
            self.assertEqual(integrations._open_stream("http://x", {"model": "m", "reasoning_effort": "xhigh"}, {}, 5), "stream")
        self.assertEqual(sent[-1], {"model": "m"})
        with mock.patch.object(integrations.urllib.request, "urlopen", side_effect=urllib.error.HTTPError("http://x", 400, "bad", {}, None)):
            with self.assertRaises(urllib.error.HTTPError):
                integrations._open_stream("http://x", {"model": "m"}, {}, 5)


class Translations(unittest.TestCase):
    def test_every_entry_is_complete(self):
        data = json.loads((ROOT / "ui/src/i18n/strings.json").read_text(encoding="utf-8"))
        for key, text in data.items():
            self.assertTrue(text.strip(), key)
            self.assertEqual(sorted(re.findall(r"\{\d\}", key)), sorted(re.findall(r"\{\d\}", text)), key)


class CommandLanguages(unittest.TestCase):
    @staticmethod
    def route(text):
        name = core.CompanionCore._detect_composer_route(text)
        return "computer" if name == "chat" and core.CompanionCore._is_computer_request(text) else name

    @staticmethod
    def allowed(action, text):
        stub = types.SimpleNamespace(_run_computer_action=lambda item, shot, display: "ok")
        return core.CompanionCore._execute_computer_actions(stub, action, None, None, text) == "ok"

    def test_every_suggestion_works_like_the_russian_one(self):
        strings = json.loads((ROOT / "ui/src/i18n/strings.json").read_text(encoding="utf-8"))
        source = (ROOT / "ui/src/transcript.tsx").read_text(encoding="utf-8")
        block = source[source.index("const SUGGESTIONS"):source.index("function Suggestions")]
        texts = re.findall(r'^\s+"(.+)",$', block, re.M)
        self.assertEqual(len(texts), 25)
        for text in texts:
            self.assertEqual(self.route(strings[text]), self.route(text), strings[text])

    def test_ordinary_questions_stay_chat(self):
        for text in ("What does open source mean?", "the open window is cold", "How do I open Notepad?",
                     "I've a question about cats", "Tell me about video games", "What type of fruit is this?",
                     "¿Qué es una ventana?", "天空为什么是蓝色的", "Отношение к кошкам"):
            self.assertEqual(self.route(text), "chat", text)

    def test_named_app_is_allowed_in_every_language(self):
        for app, text in (("Notepad", "Open Notepad"), ("Блокнот", "Открой Блокнот"), ("记事本", "打开记事本"),
                          ("Bloc de notas", "Abre el Bloc de notas"), ("Calculator", "Abre la Calculadora")):
            self.assertTrue(self.allowed({"computer_action": "open_app", "app": app}, text), text)

    def test_unasked_actions_stay_refused(self):
        for action, text in (({"computer_action": "open_app", "app": "Calculator"}, "Open Notepad"),
                             ({"computer_action": "open_app", "app": "计算器"}, "打开记事本"),
                             ({"computer_action": "web_search", "query": "x"}, "What is the weather?"),
                             ({"computer_action": "web_search", "query": "x"}, "天空为什么是蓝色的"),
                             ({"computer_action": "create_file", "path": "C:/a.txt", "content": "x"}, "Open Notepad"),
                             ({"computer_action": "create_file", "path": "C:/a.txt", "content": "x"}, "打开记事本"),
                             ({"computer_action": "press_key", "keys": "alt+f4"}, "Open Notepad"),
                             ({"computer_action": "minimize_window"}, "Abre el Bloc de notas"),
                             ({"computer_action": "open_url", "url": "evil.example"}, "Search the web for cats")):
            with self.assertRaises(ValueError, msg=text):
                self.allowed(action, text)

    def test_browser_only_on_a_direct_request(self):
        from app.chat import commands
        for text in ("Поищи рецепт борща", "Загугли погоду", "Найди в интернете новости", "Прочитай эту страницу",
                     "Открой https://example.com", "что на github.com", "Search the web for cats", "Look up llama.cpp",
                     "Busca gatos en internet", "搜索猫的图片", "上网查一下天气"):
            self.assertTrue(commands.asks_web(text), text)
        for text in ("Открой калькулятор", "Open Calculator", "Какая сегодня погода?", "Найди ошибку в коде", "What is the weather?",
                     "Create an Ideas folder on the desktop", "Abre la Calculadora", "打开计算器", "Explain how the internet works",
                     "Объясни простыми словами, как работает интернет", "用通俗的话解释互联网是如何工作的"):
            self.assertFalse(commands.asks_web(text), text)

    def test_model_can_search_but_opens_sites_only_on_a_request(self):
        source = (ROOT / "app/chat/engine.py").read_text(encoding="utf-8")
        self.assertIn("may_open_sites=commands.asks_web(prompt)", source)
        browser = mock.Mock()
        box = core.tools.ToolBox("no-app", "no-data", browser, may_open_sites=False)
        names = [spec["function"]["name"] for spec in box.specs(start_servers=False)]
        self.assertIn("web_search", names)
        self.assertNotIn("open_web_page", names)
        self.assertIn("web_search", box.skills_prompt())
        self.assertIn("прямой просьбе", box.run("open_web_page", {"url": "https://x"}))
        browser.open.assert_not_called()

    def test_search_does_not_open_the_panel(self):
        browser = mock.Mock()
        browser.search.return_value = ("Results", "text")
        box = core.tools.ToolBox("no-app", "no-data", browser, may_open_sites=False)
        self.assertIn("text", box.run("web_search", {"query": "x y"}))
        browser.search.assert_called_once_with("https://search.brave.com/search?q=x%20y")
        browser.open.assert_not_called()

    def test_asked_actions_are_allowed(self):
        for action, text in (({"computer_action": "web_search", "query": "cats"}, "Search the web for cats"),
                             ({"computer_action": "web_search", "query": "gatos"}, "Busca gatos en internet"),
                             ({"computer_action": "create_folder", "path": "C:/Ideas"}, "创建文件夹 Ideas"),
                             ({"computer_action": "press_key", "keys": "alt+f4"}, "Cierra esta ventana"),
                             ({"computer_action": "maximize_window"}, "最大化窗口")):
            self.assertTrue(self.allowed(action, text), text)


class AnswerLanguage(unittest.TestCase):
    def test_prompts_do_not_force_russian(self):
        self.assertNotIn("по-русски", core.COMPANION_SYSTEM_PROMPT)
        self.assertNotIn("по-русски", core.CompanionCore._effective_system_prompt(core.OLD_SYSTEM_PROMPTS[1]))

    def test_custom_prompt_is_kept(self):
        custom = "Отвечай только по-русски и шути."
        self.assertIn(custom, core.CompanionCore._effective_system_prompt(custom))

    def test_rule_follows_the_message_and_names_the_interface(self):
        for language, name in (("ru", "Русский"), ("en", "English")):
            rule = core.CompanionCore._language_rule(language)
            self.assertIn("последнее сообщение", rule)
            self.assertIn(name, rule)


class Preview(unittest.TestCase):
    def test_serves_the_page_from_its_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            page = Path(folder) / "index.html"
            page.write_text("<h1>ok</h1>", encoding="utf-8")
            try:
                with urllib.request.urlopen(preview.url_for(page), timeout=5) as response:
                    self.assertEqual(response.read(), b"<h1>ok</h1>")
            finally:
                preview.stop_all()


if __name__ == "__main__":
    unittest.main()

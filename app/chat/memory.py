from __future__ import annotations

import json
import math
import re
import sqlite3
import struct
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from app import processes

EMBED_REPO = "Qwen/Qwen3-Embedding-0.6B-GGUF"
EMBED_FILE = "Qwen3-Embedding-0.6B-Q8_0.gguf"
EMBED_PORT = 47870
QUERY_PREFIX = "Instruct: Given a question, retrieve earlier conversation passages and facts that help answer it\nQuery: "
WORD = re.compile(r"\w+", re.UNICODE)
STOP = set("и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня еще нет "
           "о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя "
           "ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж "
           "the a an and or of to in is are was it this that for on with as be by at from".split())


def terms(text):
    return [word[:6] for word in WORD.findall(str(text).lower()) if word not in STOP and len(word) > 1]


class Memory:
    def __init__(self, data_dir, server_exe):
        self.folder = Path(data_dir) / "memory"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.model_path = self._chosen_model()
        self.server_exe = Path(server_exe)
        self._db = sqlite3.connect(str(self.folder / "memory.sqlite"), check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS memories (id INTEGER PRIMARY KEY, kind TEXT, chat_id TEXT, text TEXT, "
                         "created REAL, vector BLOB)")
        self._db.commit()
        self._lock = threading.Lock()
        self._process = None
        self._server_lock = threading.Lock()

    def add(self, kind, text, chat_id=""):
        text = " ".join(str(text).split())[:4000]
        if not text:
            return None
        vector = self._embed(text)
        with self._lock:
            if kind == "fact" and self._db.execute("SELECT 1 FROM memories WHERE kind='fact' AND text=?", (text,)).fetchone():
                return None
            cursor = self._db.execute("INSERT INTO memories (kind, chat_id, text, created, vector) VALUES (?, ?, ?, ?, ?)",
                                      (kind, chat_id, text, time.time(), _pack(vector)))
            self._db.commit()
            return cursor.lastrowid

    def add_exchange(self, chat_id, question, answer):
        if len(str(question).strip()) < 4 or not str(answer).strip():
            return None
        return self.add("exchange", f"Пользователь: {str(question)[:1500]}\nКомпаньон: {str(answer)[:2000]}", chat_id)

    def facts(self):
        with self._lock:
            rows = self._db.execute("SELECT id, text, created FROM memories WHERE kind='fact' ORDER BY created DESC").fetchall()
        return [{"id": row[0], "text": row[1], "created": row[2]} for row in rows]

    def counts(self):
        with self._lock:
            rows = dict(self._db.execute("SELECT kind, COUNT(*) FROM memories GROUP BY kind").fetchall())
            vectors = self._db.execute("SELECT COUNT(*) FROM memories WHERE vector IS NOT NULL").fetchone()[0]
        return {"facts": rows.get("fact", 0), "exchanges": rows.get("exchange", 0), "withMeaning": vectors}

    def delete(self, entry_id):
        with self._lock:
            self._db.execute("DELETE FROM memories WHERE id=?", (int(entry_id),))
            self._db.commit()

    def forget_chat(self, chat_id):
        with self._lock:
            self._db.execute("DELETE FROM memories WHERE kind='exchange' AND chat_id=?", (str(chat_id),))
            self._db.commit()

    def clear(self, kind=None):
        with self._lock:
            self._db.execute("DELETE FROM memories" + (" WHERE kind=?" if kind else ""), (kind,) if kind else ())
            self._db.commit()

    def search(self, query, limit=4, exclude_chat=""):
        with self._lock:
            rows = self._db.execute("SELECT id, kind, chat_id, text, vector FROM memories").fetchall()
        rows = [row for row in rows if not (row[1] == "exchange" and exclude_chat and row[2] == exclude_chat)]
        if not rows:
            return []
        query_terms = terms(query)
        documents = [terms(row[3]) for row in rows]
        average = sum(map(len, documents)) / len(documents) or 1
        frequency = {}
        for document in documents:
            for term in set(document):
                frequency[term] = frequency.get(term, 0) + 1
        lexical = []
        for document in documents:
            counts = {}
            for term in document:
                counts[term] = counts.get(term, 0) + 1
            score = 0.0
            for term in set(query_terms):
                if term in counts:
                    idf = math.log(1 + (len(documents) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                    tf = counts[term]
                    score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(document) / average))
            lexical.append(score)
        top = max(lexical) or 1
        query_vector = self._embed(self.query_prefix() + str(query)) if any(row[4] for row in rows) else None
        scored = []
        for row, score in zip(rows, lexical):
            meaning = _cosine(query_vector, _unpack(row[4])) if query_vector and row[4] else None
            combined = (0.35 * score / top + 0.65 * max(0.0, (meaning - 0.3) / 0.7)) if meaning is not None else score / top
            if row[1] == "fact":
                combined += 0.08
            scored.append((combined, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        floor = 0.25 if query_vector else 0.3
        return [{"id": row[0], "kind": row[1], "text": row[3], "score": round(score, 3)}
                for score, row in scored[:limit] if score >= floor]

    def _chosen_model(self):
        folder = self.folder / "model"
        try:
            chosen = folder / (folder / "chosen.txt").read_text(encoding="utf-8").strip()
            if chosen.is_file():
                return chosen
        except OSError:
            pass
        return folder / EMBED_FILE

    def use_model(self, path):
        path = Path(path)
        (self.folder / "model" / "chosen.txt").write_text(path.name, encoding="utf-8")
        self.stop()
        self.model_path = path
        with self._lock:
            self._db.execute("UPDATE memories SET vector=NULL")
            self._db.commit()
        self._remove_other_models(path)

    def _remove_other_models(self, keep):
        for item in (self.folder / "model").iterdir():
            if item.is_file() and item.name != Path(keep).name and item.suffix.lower() in (".gguf", ".download"):
                try:
                    item.unlink()
                except OSError:
                    pass

    def query_prefix(self):
        name = self.model_path.name.lower()
        if "qwen3-embedding" in name:
            return QUERY_PREFIX
        if "e5" in name:
            return "query: "
        if "nomic" in name:
            return "search_query: "
        if "embeddinggemma" in name:
            return "task: search result | query: "
        return ""

    def model_ready(self):
        return self.model_path.is_file() and self.model_path.stat().st_size > 100 * 2**20

    def _server(self):
        if not self.model_ready() or not self.server_exe.is_file():
            return None
        with self._server_lock:
            if self._process is None or self._process.poll() is not None:
                args = [str(self.server_exe), "-m", str(self.model_path), "--host", "127.0.0.1", "--port", str(EMBED_PORT),
                        "--embedding", "-ngl", "0", "-c", "2048", "-np", "1", "--no-webui"]
                self._process = processes.own(subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)))
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{EMBED_PORT}/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except Exception:
                        time.sleep(0.4)
            return f"http://127.0.0.1:{EMBED_PORT}"

    def _embed(self, text):
        url = self._server()
        if url is None:
            return None
        try:
            body = json.dumps({"input": str(text)[:6000], "model": "memory"}).encode("utf-8")
            request = urllib.request.Request(url + "/v1/embeddings", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=30) as response:
                vector = json.loads(response.read().decode("utf-8"))["data"][0]["embedding"]
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            return [value / norm for value in vector]
        except Exception:
            return None

    def index_missing(self, progress=lambda done, total: None):
        with self._lock:
            rows = self._db.execute("SELECT id, text FROM memories WHERE vector IS NULL").fetchall()
        for done, (entry_id, text) in enumerate(rows, 1):
            vector = self._embed(text)
            if vector is None:
                return
            with self._lock:
                self._db.execute("UPDATE memories SET vector=? WHERE id=?", (_pack(vector), entry_id))
                self._db.commit()
            progress(done, len(rows))

    def stop(self):
        if self._process is not None and self._process.poll() is None:
            self._process.kill()


def _pack(vector):
    return struct.pack(f"<{len(vector)}f", *vector) if vector else None


def _unpack(blob):
    return list(struct.unpack(f"<{len(blob) // 4}f", blob)) if blob else None


def _cosine(a, b):
    if not a or not b or len(a) != len(b):
        return None
    return sum(x * y for x, y in zip(a, b))

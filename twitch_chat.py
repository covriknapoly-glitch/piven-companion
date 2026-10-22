"""Conservative, user-confirmed Twitch chat sender for PIVEN Companion."""
from __future__ import annotations

import json
import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QThread, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QMessageBox,
)


API = "https://api.twitch.tv/helix"
VALIDATE = "https://id.twitch.tv/oauth2/validate"
MIN_INTERVAL = 20
MAX_PER_HOUR = 3
MAX_PER_DAY = 10
MAX_MESSAGE_CHARS = 300


def _request(url: str, token: str, client_id: str | None = None,
             payload: dict | None = None, validate: bool = False) -> dict:
    headers = {"Authorization": ("OAuth " if validate else "Bearer ") + token}
    if client_id:
        headers["Client-Id"] = client_id
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        if exc.code == 429:
            raise RuntimeError("Twitch отклонил запрос по лимиту. Отправка остановлена; повторных попыток не будет.")
        if exc.code in (401, 403):
            raise RuntimeError("Twitch не разрешил отправку. Проверь токен, scope user:write:chat и доступ к каналу.")
        raise RuntimeError(f"Twitch вернул ошибку {exc.code}: {detail}")


def _send_once(channel: str, message: str, token: str) -> str:
    validation = _request(VALIDATE, token, validate=True)
    client_id = validation.get("client_id")
    sender_id = validation.get("user_id")
    scopes = validation.get("scopes", [])
    if not client_id or not sender_id:
        raise RuntimeError("Twitch не вернул данные учётной записи для этого токена.")
    if "user:write:chat" not in scopes:
        raise RuntimeError("Токену не выдано разрешение user:write:chat.")
    query = urllib.parse.urlencode({"login": channel})
    users = _request(f"{API}/users?{query}", token, client_id)
    entries = users.get("data", [])
    if not entries:
        raise RuntimeError(f"Канал «{channel}» не найден.")
    broadcaster_id = entries[0]["id"]
    result = _request(f"{API}/chat/messages", token, client_id, {
        "broadcaster_id": broadcaster_id,
        "sender_id": sender_id,
        "message": message,
    })
    sent = (result.get("data") or [{}])[0]
    if not sent.get("is_sent", False):
        reason = sent.get("drop_reason") or {}
        raise RuntimeError(reason.get("message") or "Twitch не отправил это сообщение.")
    return f"Отправлено в #{channel}."


class _SendWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, channel: str, message: str, token: str, parent=None):
        super().__init__(parent)
        self.channel, self.message, self.token = channel, message, token

    def run(self):
        try:
            self.done.emit(True, _send_once(self.channel, self.message, self.token))
        except Exception as exc:
            self.done.emit(False, str(exc))


class TwitchChatDialog(QDialog):
    """A deliberate one-message-at-a-time chat UI with persistent local caps."""

    def __init__(self, parent, settings: dict, save_settings, accent="#ffffff"):
        super().__init__(parent)
        self.settings = settings
        self.save_settings = save_settings
        self.token = ""  # Keep OAuth credentials in memory only.
        self.worker = None
        self.setWindowTitle("PIVEN · Twitch")
        self.setMinimumWidth(520)
        self.setStyleSheet(f"""
            QDialog {{ background:#0b0b0b; color:#f5f5f5; }}
            QLabel {{ color:#ededed; }}
            QLineEdit, QPlainTextEdit {{ background:#111; color:#fff; border:1px solid #484848; padding:9px; selection-background-color:#555; }}
            QPushButton {{ background:#191919; color:#fff; border:1px solid #484848; padding:9px 12px; }}
            QPushButton:hover {{ border-color:{accent}; }}
            QPushButton:disabled {{ color:#777; }}
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)
        title = QLabel("TWITCH  /  ЧАТ")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        outer.addWidget(title)
        note = QLabel("Компаньон отправит только текст, который ты введёшь здесь и отдельно подтвердишь.")
        note.setWordWrap(True)
        outer.addWidget(note)

        form = QFormLayout()
        self.channel = QLineEdit(str(settings.get("twitch_channel", "")))
        self.channel.setPlaceholderText("например: twitchdev")
        form.addRow("Канал", self.channel)
        self.token_box = QLineEdit()
        self.token_box.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_box.setPlaceholderText("OAuth access token со scope user:write:chat")
        self.token_box.textChanged.connect(self._token_changed)
        form.addRow("Токен", self.token_box)
        outer.addLayout(form)
        help_link = QPushButton("Как получить токен Twitch")
        help_link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://dev.twitch.tv/docs/chat/authenticating/")))
        outer.addWidget(help_link, alignment=Qt.AlignmentFlag.AlignLeft)
        token_note = QLabel("Токен нужен для отправки и хранится только в памяти до закрытия Компаньона.")
        token_note.setWordWrap(True)
        outer.addWidget(token_note)

        self.message = QPlainTextEdit()
        self.message.setPlaceholderText("Текст одного сообщения…")
        self.message.textChanged.connect(self._update_count)
        self.message.setFixedHeight(92)
        outer.addWidget(self.message)
        self.counter = QLabel(f"0 / {MAX_MESSAGE_CHARS}")
        outer.addWidget(self.counter, alignment=Qt.AlignmentFlag.AlignRight)
        self.status = QLabel(self._limit_status())
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.send_button = QPushButton("Отправить одно сообщение")
        self.send_button.clicked.connect(self._confirm_send)
        buttons.addWidget(self.send_button)
        close_button = QPushButton("Закрыть")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        outer.addLayout(buttons)
        self._update_count()

    def _token_changed(self, value):
        self.token = value.strip()
        self._update_count()

    def _entries(self):
        now = time.time()
        raw = self.settings.get("twitch_send_history", [])
        entries = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    try:
                        stamp = float(item.get("time", 0))
                        if 0 <= now - stamp < 86400:
                            entries.append({"time": stamp, "fingerprint": str(item.get("fingerprint", ""))})
                    except (TypeError, ValueError):
                        pass
        return entries

    def _limit_status(self):
        entries = self._entries()
        now = time.time()
        last = max((e["time"] for e in entries), default=0)
        if last and now - last < MIN_INTERVAL:
            return f"Защита от спама: подожди {int(MIN_INTERVAL - (now - last)) + 1} сек. Лимит: не чаще 1 сообщения в 20 секунд, 3 в час, 10 в сутки."
        hour = sum(now - e["time"] < 3600 for e in entries)
        day = len(entries)
        if hour >= MAX_PER_HOUR or day >= MAX_PER_DAY:
            return f"Лимит достигнут: {hour}/{MAX_PER_HOUR} за час, {day}/{MAX_PER_DAY} за сутки."
        return f"Осталось: {MAX_PER_HOUR-hour} за час, {MAX_PER_DAY-day} за сутки. Между отправками — минимум 20 секунд."

    def _reserve_slot(self, message):
        entries = self._entries()
        now = time.time()
        if entries and now - max(e["time"] for e in entries) < MIN_INTERVAL:
            return False, self._limit_status()
        if sum(now - e["time"] < 3600 for e in entries) >= MAX_PER_HOUR:
            return False, "Достигнут предел: максимум три сообщения за скользящий час."
        if len(entries) >= MAX_PER_DAY:
            return False, "Достигнут предел: максимум десять сообщений за скользящие сутки."
        fingerprint = hashlib.sha256(message.casefold().encode("utf-8")).hexdigest()
        if any(e["fingerprint"] == fingerprint for e in entries):
            return False, "Такой же текст уже отправлялся за последние сутки. Повтор заблокирован."
        entries.append({"time": now, "fingerprint": fingerprint})
        self.settings["twitch_send_history"] = entries
        self.settings["twitch_channel"] = self.channel.text().strip().lstrip("#")
        self.save_settings()
        return True, ""

    def _update_count(self):
        length = len(self.message.toPlainText())
        self.counter.setText(f"{length} / {MAX_MESSAGE_CHARS}")
        self.send_button.setEnabled(length > 0 and length <= MAX_MESSAGE_CHARS and bool(self.token) and not (self.worker and self.worker.isRunning()))

    def _confirm_send(self):
        channel = self.channel.text().strip().lstrip("#")
        message = self.message.toPlainText().strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{1,25}", channel):
            QMessageBox.warning(self, "Twitch", "Введи название Twitch-канала: только латинские буквы, цифры и _. ")
            return
        if not self.token:
            QMessageBox.warning(self, "Twitch", "Сначала вставь OAuth-токен с разрешением user:write:chat.")
            return
        if not message or len(message) > MAX_MESSAGE_CHARS:
            return
        answer = QMessageBox.question(
            self, "Подтверди отправку",
            f"Отправить в Twitch-канал #{channel} ровно одно сообщение?\n\n{message}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        allowed, why = self._reserve_slot(message)
        if not allowed:
            QMessageBox.information(self, "Защита от спама", why)
            self.status.setText(self._limit_status())
            return
        self.send_button.setEnabled(False)
        self.channel.setEnabled(False)
        self.token_box.setEnabled(False)
        self.message.setEnabled(False)
        self.status.setText("Отправляю одно сообщение… Повторной попытки автоматически не будет.")
        self.worker = _SendWorker(channel, message, self.token, self)
        self.worker.done.connect(self._send_finished)
        self.worker.start()

    def _send_finished(self, success: bool, message: str):
        self.channel.setEnabled(True)
        self.token_box.setEnabled(True)
        self.message.setEnabled(True)
        self.status.setText(("✓ " if success else "Не отправлено: ") + message + "\n" + self._limit_status())
        self.message.clear()
        self._update_count()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.status.setText("Дождись ответа Twitch: запрос уже отправляется, повторять его нельзя.")
            event.ignore()
            return
        event.accept()


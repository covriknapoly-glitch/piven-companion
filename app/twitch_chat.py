"""Conservative, user-confirmed Twitch chat sender for PIVEN Companion."""
from __future__ import annotations

import re

from PySide6.QtCore import QThread, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QMessageBox,
)

from twitch_core import MAX_MESSAGE_CHARS, limit_status, reserve_slot, send_once


class _SendWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, channel: str, message: str, token: str, parent=None):
        super().__init__(parent)
        self.channel, self.message, self.token = channel, message, token

    def run(self):
        try:
            self.done.emit(True, send_once(self.channel, self.message, self.token))
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

    def _limit_status(self):
        return limit_status(self.settings)

    def _reserve_slot(self, message):
        return reserve_slot(self.settings, self.channel.text().strip().lstrip("#"), message, self.save_settings)

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


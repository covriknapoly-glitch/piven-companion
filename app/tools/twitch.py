from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

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
            raise RuntimeError("Twitch не разрешил действие. Проверь токен, его разрешения и доступ к каналу "
                               "(опросы доступны только каналам-партнёрам и компаньонам Twitch).")
        raise RuntimeError(f"Twitch вернул ошибку {exc.code}: {detail}")


def send_once(channel: str, message: str, token: str) -> str:
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


def create_poll(channel: str, question: str, choices: list, seconds: int, token: str) -> str:
    validation = _request(VALIDATE, token, validate=True)
    client_id, user_id = validation.get("client_id"), validation.get("user_id")
    if not client_id or not user_id:
        raise RuntimeError("Twitch не вернул данные учётной записи для этого токена.")
    if "channel:manage:polls" not in validation.get("scopes", []):
        raise RuntimeError("Токену не выдано разрешение channel:manage:polls.")
    if str(validation.get("login", "")).lower() != channel.lower():
        raise RuntimeError("Опрос можно запустить только на своём канале: токен принадлежит другому каналу.")
    question = " ".join(str(question).split())[:60]
    choices = [" ".join(str(item).split())[:25] for item in choices if str(item).strip()][:5]
    if not question or not 2 <= len(choices) <= 5:
        raise RuntimeError("Нужен вопрос до 60 символов и от 2 до 5 вариантов до 25 символов.")
    result = _request(f"{API}/polls", token, client_id, {
        "broadcaster_id": user_id, "title": question,
        "choices": [{"title": item} for item in choices], "duration": max(15, min(1800, int(seconds))),
    })
    if not result.get("data"):
        raise RuntimeError("Twitch не создал опрос.")
    return f"Опрос запущен на канале {channel}: «{question}»."


def history(settings: dict) -> list[dict]:
    now = time.time()
    raw = settings.get("twitch_send_history", [])
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


def limit_status(settings: dict) -> str:
    entries = history(settings)
    now = time.time()
    last = max((e["time"] for e in entries), default=0)
    if last and now - last < MIN_INTERVAL:
        return f"Защита от спама: подожди {int(MIN_INTERVAL - (now - last)) + 1} сек. Лимит: не чаще 1 сообщения в 20 секунд, 3 в час, 10 в сутки."
    hour = sum(now - e["time"] < 3600 for e in entries)
    day = len(entries)
    if hour >= MAX_PER_HOUR or day >= MAX_PER_DAY:
        return f"Лимит достигнут: {hour}/{MAX_PER_HOUR} за час, {day}/{MAX_PER_DAY} за сутки."
    return f"Осталось: {MAX_PER_HOUR-hour} за час, {MAX_PER_DAY-day} за сутки. Между отправками — минимум 20 секунд."


def valid_channel(channel: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_]{1,25}", channel or ""))


def reserve_slot(settings: dict, channel: str, message: str, save) -> tuple[bool, str]:
    entries = history(settings)
    now = time.time()
    if entries and now - max(e["time"] for e in entries) < MIN_INTERVAL:
        return False, limit_status(settings)
    if sum(now - e["time"] < 3600 for e in entries) >= MAX_PER_HOUR:
        return False, "Достигнут предел: максимум три сообщения за скользящий час."
    if len(entries) >= MAX_PER_DAY:
        return False, "Достигнут предел: максимум десять сообщений за скользящие сутки."
    fingerprint = hashlib.sha256(message.casefold().encode("utf-8")).hexdigest()
    if any(e["fingerprint"] == fingerprint for e in entries):
        return False, "Такой же текст уже отправлялся за последние сутки. Повтор заблокирован."
    entries.append({"time": now, "fingerprint": fingerprint})
    settings["twitch_send_history"] = entries
    settings["twitch_channel"] = channel
    save()
    return True, ""

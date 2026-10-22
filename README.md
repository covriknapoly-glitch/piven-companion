# PIVEN Companion

Локальный компаньон для Windows: разговаривает через Ollama, рисует через ComfyUI, собирает презентации, работает с кодом в выбранной папке, слушает микрофон и озвучивает ответы. Всё работает на этом компьютере.

Два интерфейса над одним движком:

- `desktop_companion.pyw` — обычное окно на PySide6 (полный набор функций, включая микрофон и экран).
- `web_companion.pyw` — новый интерфейс: React-страница `modern-ui/dist` в окне pywebview.

Одновременно открывается только одно окно, чтобы они не перезаписали чаты друг друга.

## Что в репозитории

| Путь | Что это |
|---|---|
| `companion_core.py` | Движок без Qt: настройки, чаты, Ollama, ComfyUI, голос, навыки |
| `desktop_companion.pyw`, `web_companion.pyw` | Два интерфейса |
| `computer_skill.py`, `presentation_skill.py`, `twitch_chat.py` | Навыки |
| `modern-ui/` | Исходники веб-интерфейса (`src/`) и готовая сборка (`dist/`) |
| `skills/computer-control/` | Инструкция для модели и справка по устройству программы |
| `assets/` | Логотип, иконки, шрифты |
| `Qwen-Image-*.json` | Workflow ComfyUI для картинок |
| `kitten-tts-openwebui/`, `qwen3-tts-openwebui/` | Только скрипты запуска голосовых серверов |

Нейросети в репозиторий не входят: модели и окружения Qwen3-TTS и Parakeet, ComfyUI, Ollama. Также не входят вложенный Python и библиотеки — их ставит инструкция ниже.

## Установка

1. **Python 3.11 x64.** Можно положить его в `runtime\Python311` (тогда ярлыки возьмут его) или использовать установленный.
2. **Библиотеки** рядом с программой:
   ```
   runtime\Python311\python.exe -m pip install --target .packages -r requirements.txt
   ```
   Программа читает пакеты из `.packages` и `.qt_runtime` и не смотрит в пользовательские site-packages.
3. **Ollama** с хотя бы одной моделью — для разговора, кода и презентаций.
4. **ComfyUI** (Comfy Desktop) — для картинок. Адрес и workflow настраиваются в программе.
5. **Голос (по желанию).** Распознавание речи: NeMo-Speech с моделью Parakeet в `kitten-tts-openwebui/nemo-speech` и `kitten-tts-openwebui/models`. Озвучка: Qwen3-TTS, сервер `qwen3-tts-openwebui/server.py` в окружении `kitten-tts-openwebui/.venv`. Подробности — в README этих папок.

## Запуск

- `Запустить компаньон.cmd` — обычное окно.
- `Запустить веб-интерфейс.cmd` — веб-интерфейс.

Настройки, чаты, журналы и картинки хранятся в `%LOCALAPPDATA%\OllamaCompanion`, а не в папке программы.

## Сборка веб-интерфейса

После правок в `modern-ui/src` пересобери `dist`: `modern-ui\scripts\build.cmd`. Скрипт использует `esbuild` из `modern-ui/node_modules` (в git не входит). Поставить зависимости можно через Node.js: `npm install` в папке `modern-ui`.

Подробнее о возможностях — в `README_Компаньон.md`.

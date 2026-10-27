# PIVEN Companion

Локальный компаньон для Windows: разговаривает с локальными моделями через llama.cpp, рисует через ComfyUI, собирает презентации, работает с кодом в выбранной папке, слушает микрофон и озвучивает ответы. Всё работает на этом компьютере.

Два интерфейса над одним движком:

- **Веб-интерфейс** — React-страница `modern-ui/dist` в окне pywebview (`app/web_companion.pyw`).
- **Обычное окно** на PySide6 (`app/desktop_companion.pyw`).

Одновременно открывается только одно окно, чтобы они не перезаписали чаты друг друга.

## Структура

```
Запустить веб-интерфейс.cmd   запуск веб-интерфейса
Запустить компаньон.cmd       запуск обычного окна
requirements.txt              библиотеки Python
app/                          код программы
  companion_core.py           движок без интерфейса: настройки, чаты, модели, голос, навыки
  web_companion.pyw           веб-интерфейс (pywebview)
  desktop_companion.pyw       обычное окно (PySide6)
  llama_backend.py            запуск llama-server и разговор с моделью
  hf_models.py                поиск и скачивание моделей с Hugging Face
  voice_install.py            голосовые модели: поиск, скачивание, удаление
  voice_engines.py            установка голосовых движков
  audiocpp_catalog.py         каталог моделей audio.cpp
  memory_estimate.py          оценка видеопамяти
  computer_skill.py           управление компьютером
  presentation_skill.py       презентации PowerPoint
  twitch_chat.py, twitch_core.py   Twitch
  native_browser.py, model_logos.py, process_job.py   вспомогательное
modern-ui/                    веб-интерфейс: исходники (src/) и готовая сборка (dist/)
qwen3-tts-openwebui/          голосовые серверы (hf_voice_server.py, server.py)
kitten-tts-openwebui/         скрипты распознавания речи
skills/computer-control/      инструкция для модели и справка по устройству программы
assets/                       иконки и шрифты
docs/                         подробное описание и список вложенных зависимостей
```

Нейросети в репозиторий не входят: модели, голосовые движки и их окружения, llama.cpp, ComfyUI. Не входят и вложенный Python с библиотеками — их ставит инструкция ниже.

## Установка

1. **Python 3.11 x64** в `runtime\Python311` (его возьмут ярлыки) или установленный.
2. **Библиотеки** рядом с программой:
   ```
   runtime\Python311\python.exe -m pip install --target .packages -r requirements.txt
   ```
   Программа читает пакеты из `.packages` и `.qt_runtime` и не смотрит в пользовательские site-packages.
3. **llama.cpp**: `llama.cpp\bin\llama-server.exe`. Модели GGUF скачиваются в программе («Скачать модель с Hugging Face»).
4. **Голос (по желанию)**: движки и модели озвучки и распознавания ставятся в настройках программы.
5. **ComfyUI** (по желанию) — для картинок. Адрес и workflow указываются в настройках.

## Запуск

- `Запустить веб-интерфейс.cmd` — веб-интерфейс.
- `Запустить компаньон.cmd` — обычное окно.

Настройки, чаты, журналы и картинки хранятся в `%LOCALAPPDATA%\OllamaCompanion`, а не в папке программы.

## Сборка веб-интерфейса

После правок в `modern-ui/src` пересобери `dist`: `modern-ui\scripts\build.cmd`. Скрипт берёт `esbuild` из `modern-ui/node_modules` (в git не входит; `npm install` в папке `modern-ui`). Если есть портативный Node.js в `runtime\node`, перед сборкой идёт проверка типов TypeScript.

Подробнее о возможностях — в [docs/README_Компаньон.md](docs/README_Компаньон.md).

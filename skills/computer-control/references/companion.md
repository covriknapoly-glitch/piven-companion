# PIVEN Companion: how the program is organized

## Folders

- `app/chat/engine.py` — the engine: settings, chats, `ask_model`, computer control, presentations, images, speech. It reports results to the window through the `events` queue.
- `app/chat/memory.py` — long-term memory.
- `app/models/` — `llama.py` (local models through llama-server), `integrations.py` (Ollama, LM Studio, cloud services), `huggingface.py` (model search and download).
- `app/tools/` — `computer.py` (computer and project commands), `presentation.py`, `toolbox.py` (the model's tools and skills), `mcp.py`.
- `app/voice/` — installing and running voice models.
- `app/window/main.pyw` — the window. The `WebApi` class holds the methods the page calls.
- `ui/src/` — the React interface; rebuild with `ui/scripts/build.cmd` after changes.
- `skills/` — instructions for the model; `tests/` — engine checks.
- Settings, chats and logs are in `%LOCALAPPDATA%/PIVEN`. Do not touch them without a direct request.
- `Архив/` — old versions; nothing there is run.

## Rules

- Before changing anything, find the function and read it; this note is only a map.
- Computer actions run only on an explicit request; downloads always ask for confirmation and never overwrite files.
- Do not run downloaded files, install dependencies or execute arbitrary shell code.
- After Python changes, run `python -m unittest discover -s tests`. Changes take effect only after the program restarts.

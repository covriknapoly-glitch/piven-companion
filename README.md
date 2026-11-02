<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
  <img src="docs/images/logo-light.svg" alt="PIVEN logo" width="120">
</picture>

# PIVEN Companion

**A personal AI companion that runs on your own computer.**<br>
Chat, talk, draw, search the web and get things done — with local models, no subscription and no data leaving your PC.

[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)
![Windows 10/11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)
![llama.cpp](https://img.shields.io/badge/runs%20on-llama.cpp-8A2BE2)
![Free forever](https://img.shields.io/badge/price-free%20forever-2ea44f)

[Features](#-features) · [Install](#-install) · [First steps](#-first-steps) · [Privacy](#-privacy) · [For developers](#-for-developers)

<img src="docs/images/main-window.svg" alt="PIVEN Companion main window" width="900">

</div>

---

## ✨ Features

<table>
<tr>
<td width="50%" valign="top">

### 🧠 Local models, made easy
Search Hugging Face right inside the app and download any GGUF model in one click. Before downloading you see **how much video memory and RAM it needs and how fast it will run** on your hardware. Models run through llama.cpp on your GPU, with automatic speed-ups where the model supports them.

</td>
<td width="50%" valign="top">

### 🎙️ Voice and calls
Talk to the companion out loud and hear it answer. Start a **call** for a hands-free conversation, sentence by sentence. 14 voice engines to choose from — Qwen3-TTS, Whisper, Kokoro, Chatterbox, XTTS, Piper and more — installed from the settings with one button.

</td>
</tr>
<tr>
<td valign="top">

### 🛠️ It can actually do things
The model uses tools on its own: searches and reads web pages in the built-in browser, runs Python / PowerShell / JavaScript to check its answers, works with files in your project folder, makes **PowerPoint presentations** with a matching design, and opens apps, folders and sites on your PC.

</td>
<td valign="top">

### 🎨 Pictures and video
Ask for a picture or a short video and it is drawn through **ComfyUI** with the workflow you choose. Attach an image to turn it into a video.

</td>
</tr>
<tr>
<td valign="top">

### 💾 Long-term memory
The companion remembers important facts and finds earlier conversations when they matter. An optional small embedding model lets it search **by meaning**, not just by words. You can see, add and delete everything it remembers.

</td>
<td valign="top">

### 🔌 Plug in anything
Use models from **Ollama, LM Studio, OpenAI, Gemini, OpenRouter, Anthropic** or any OpenAI-compatible server next to your local ones. Connect **MCP servers** and write your own **skills**. Stream on Twitch? The companion can read the chat and run viewer polls.

</td>
</tr>
</table>

**And also:** several chats working at the same time, each with its own model · real thinking modes for models that support them · images in chat for vision models · notifications from the system tray · light and dark themes · interface in English, Русский, 中文 and Español.

## 📸 Screenshots

<table>
<tr>
<td width="50%"><img src="docs/images/models.svg" alt="Downloading a model with memory and speed estimate"><br><sub><b>Pick a model</b> — with a memory and speed estimate for your PC</sub></td>
<td width="50%"><img src="docs/images/tools.svg" alt="The model searching the web and using tools"><br><sub><b>Tools</b> — the model searches, reads and runs code by itself</sub></td>
</tr>
<tr>
<td><img src="docs/images/voice.svg" alt="Voice engines and call mode"><br><sub><b>Voice</b> — speech recognition and text-to-speech</sub></td>
<td><img src="docs/images/settings.svg" alt="Settings"><br><sub><b>Settings</b> — context size, thinking modes and more</sub></td>
</tr>
</table>

## 📦 Install

### The easy way — installer

1. Download **`PIVEN-Companion-<version>-Setup.exe`** from the [Releases](https://github.com/covriknapoly-glitch/piven-companion/releases) page.
2. Run it. No administrator rights needed — it installs for your user only.
3. Open **PIVEN Companion** from the Start menu.

The installer already contains everything the program needs (Python, llama.cpp and libraries). Models are **not** included — you choose and download them inside the app.

### What you need

| | |
|---|---|
| **System** | Windows 10 or 11, 64-bit |
| **Graphics card** | NVIDIA with a recent driver recommended. Without one, models run on the processor — slower, but they work. |
| **Memory** | Depends on the model. The app shows what each model needs before you download it, and recommends one that fits. |
| **Disk** | About 1.2 GB for the program, plus your models (usually 2–20 GB each). |
| **WebView2** | Built into Windows 11. On Windows 10 the installer offers to get it if it is missing. |

## 🚀 First steps

1. **Get a model.** On first launch the app recommends a model that fits your graphics card. Click download, or search Hugging Face for any other.
2. **Say hello.** Type in the chat box, or press the microphone button and speak.
3. **Turn on what you like** in **Settings**:
   - **Voice and microphone** — install a voice and a speech recognizer.
   - **Pictures and video** — point the app at ComfyUI and your workflows.
   - **Memory** — let the companion remember things between chats.
   - **Integrations** — add cloud models, Ollama or LM Studio, and Twitch.
   - **Tools and skills** — choose a project folder, connect MCP servers, add skills.

## 🔒 Privacy

- **Everything runs on your computer.** Chats, settings and memory are stored in `%LOCALAPPDATA%\OllamaCompanion` and never leave it.
- **Nothing is downloaded without asking.** Every model shows its size and license before you click download.
- **Cloud is opt-in.** Messages go to OpenAI, Gemini or another service only if you add that provider yourself. API keys are encrypted with Windows (DPAPI).
- **You stay in control.** Downloading files and sending messages to Twitch always wait for your confirmation.

## 👩‍💻 For developers

<details>
<summary><b>Run from source</b></summary>

1. Put **Python 3.11 x64** in `runtime\Python311` (the launch scripts use it), or use an installed one.
2. Install the libraries next to the program:
   ```
   runtime\Python311\python.exe -m pip install --target .packages -r requirements.txt
   ```
   The app reads packages from `.packages` and ignores the user's site-packages.
3. Put **llama.cpp** in `llama.cpp\bin` (the app starts `llama-server.exe` from there).
4. Start `Запустить PIVEN.cmd`.

</details>

<details>
<summary><b>Build the interface</b></summary>

After editing `ui/src`, rebuild `ui/dist`:

```
ui\scripts\build.cmd
```

The script uses `esbuild` from `ui/node_modules` (run `npm install` in `ui` first). With a portable Node.js in `runtime\node` it also type-checks the TypeScript.

</details>

<details>
<summary><b>Build the installer</b></summary>

With [Inno Setup](https://jrsoftware.org/isinfo.php) 6.3 or newer:

```
"%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" installer\piven.iss
```

The result is `installer\Output\PIVEN-Companion-<version>-Setup.exe`. It packs the program, the bundled Python with its libraries and llama.cpp from this folder — never models or voice engines.

</details>

<details>
<summary><b>Project layout</b></summary>

```
app/
  chat/       engine.py (chats, answers, settings), memory.py (long-term memory)
  models/     llama.py (local models), integrations.py (Ollama, LM Studio, cloud),
              huggingface.py, download.py, memory_fit.py, logos.py
  voice/      engines.py, install.py, catalog.py
  tools/      computer.py, presentation.py, toolbox.py, mcp.py, preview.py, video.py, twitch.py
  window/     main.pyw (the window), browser.py, tray.py, workspace.py
ui/           the interface: src/ and the built dist/
voice-engines/  voice model servers
skills/       instructions for the model
tests/        python -m unittest discover -s tests
installer/    the Inno Setup script
assets/, docs/
Запустить PIVEN.cmd
```

Models, voice engines and the bundled runtimes are not in the repository.

</details>

## 📄 License

PIVEN Companion is **free software** under the [GNU GPL v3](LICENSE) or later.
You can use, change and share it for free — and any changed version must stay free and open source too.
Third-party components and their licenses are listed in [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md).

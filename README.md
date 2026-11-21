<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
  <img src="docs/images/logo-light.svg" alt="PIVEN logo" width="120">
</picture>

# PIVEN Companion

Ai agent for Windows that runs on your own pc.

[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)
![Windows 10/11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)

<img src="docs/images/main-window.png" alt="PIVEN main window" width="900">

</div>

## What is this

I wanted an ai agent that works better than opencode and easier to use, so I made one.

You can download almost any model from Hugging Face right in the app. Before downloading it tells you if the model will fit and how fast it will be.

## What it can do

- Chat by text or voice. You can also just call it and talk.
- Search the internet, open programs and create files in folder you choose.
- Make presentations.
- Draw pictures and short videos if you have ComfyUI.
- Remember stuff between chats. You can see and delete everything it remembers.
- Continue from an earlier message in a separate chat branch.
- Connect a folder of project documents and open the passages cited in answers.
- Browse project files and reuse project notes across coding chats that use the same folder.
- Connect models from Ollama, LM Studio, vLLM, Strata, Unsloth Studio, OpenRouter, Google, OpenAI, and Anthropic.

Supported languages are English and Russian.

<table>
<tr>
<td width="50%"><img src="docs/images/tools.png" alt="the agent writing a program"><br><sub>Writes programs</sub></td>
<td width="50%"><img src="docs/images/models.png" alt="model settings"><br><sub>Shows if a model fits</sub></td>
</tr>
<tr>
<td><img src="docs/images/voice.png" alt="voice settings"><br><sub>Voice and calls</sub></td>
<td><img src="docs/images/settings.png" alt="language and themes"><br><sub>Themes</sub></td>
</tr>
</table>

## How to install

1. Download `PIVEN-Companion-<version>-Setup.exe` from [releases](https://github.com/covriknapoly-glitch/piven-companion/releases).
2. Run it.

You need:

- Windows 10 or 11
- An NVIDIA card is best. Without one it still works but slower.
- About 1.2 GB for the app and more for models.

When you open it, it suggests a model for your pc. In case you want another model, you can go to settings and download any model from Hugging Face.

### Coding projects

Open a project in coding mode and choose its folder. In the right panel, **Files → Project** lets you browse folders, preview text files, and insert a file path into the chat draft.

PIVEN reads the current file layout and the first available guide from `AGENTS.md`, `CLAUDE.md`, or `README.md`. It indexes project documentation and lets the agent save verified notes for future chats in the same folder. Open **Project memory** under **Files** to see notes, remove them, or refresh the document index after external changes. The index and notes are stored locally. When you select a cloud model, relevant excerpts can be included in its request.

### Connect vLLM

Start vLLM with a chat model. In PIVEN, open **Settings → Integrations → vLLM**, turn it on, and set the server address. The default is `http://127.0.0.1:8000/v1`. Enter an API key if the server requires one. The server's models will appear in the chat model picker. [vLLM server setup](https://docs.vllm.ai/en/stable/serving/online_serving/openai_compatible_server/)

To use tools through vLLM, start the server with `--enable-auto-tool-choice` and `--tool-call-parser` for your model. [vLLM tool calling](https://docs.vllm.ai/en/stable/features/tool_calling/)

### Connect Strata or Unsloth Studio

Open **Settings → Integrations → Local models** in PIVEN and enable the server you want to use. Its models appear in the chat model picker.

- **Strata** defaults to `http://127.0.0.1:8080/v1`. Start Strata with a chat model and enter the API key if you configured one. [Strata setup](https://github.com/Niko1221/Strata/blob/main/docs/INSTALL.md)
- **Unsloth Studio** defaults to `http://127.0.0.1:8888/v1`. Load a chat model in Studio and copy the key from **Settings → API**. If Studio uses a different port, enter its address in PIVEN. After changing the loaded model, click **Reconnect** in PIVEN. [Unsloth Studio API](https://unsloth.ai/docs/basics/api)

## Your data

- Everything stays on your pc in `%LOCALAPPDATA%\PIVEN`.
- Nothing downloads unless you say so.
- If you use a cloud model, your messages go to that service. On a call that includes screenshots and what it hears, so tell people if you're on a call with them.
- Only copy your own voice or the voice of someone who gave their permission.
- Pictures and videos made in the app have a hidden mark that says ai made them.

## If you want to build it

1. Put Python 3.11 in `runtime\Python311`.
2. Run `runtime\Python311\python.exe -m pip install --target .packages -r requirements.txt`
3. Put llama.cpp in `llama.cpp\bin`.
4. Run `Запустить PIVEN.cmd`.

If you change the interface, run `npm install` in `ui` once and then `ui\scripts\build.cmd`.

## Rules

You pick the models, voices and services, and what you do with them is on you. I don't make them and I'm not connected to them. See [TERMS.txt](TERMS.txt).

## License

GPL v3 or later. It's free. If you share a changed version it has to stay open too. Other people's stuff and its licenses are in [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md).

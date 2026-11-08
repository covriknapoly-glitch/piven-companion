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
- Also, you can connect models from Ollama, LM Studio, OpenRouter, Google, OpenAI, Anthropic.

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

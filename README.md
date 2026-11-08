<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
  <img src="docs/images/logo-light.svg" alt="PIVEN logo" width="120">
</picture>

# PIVEN Companion

A local AI chat for Windows. It runs models on your own computer.

[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)
![Windows 10/11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)
![llama.cpp](https://img.shields.io/badge/runs%20on-llama.cpp-8A2BE2)

<img src="docs/images/main-window.png" alt="PIVEN Companion main window" width="900">

</div>

## What it is

I wanted a neural network chat that works offline, keeps my messages on my PC and can use the computer.

You download a model right in the app, and it runs on your graphics card through llama.cpp. Before you download a model, the app shows whether it fits in your memory and how fast it will run.

## What it can do

- Chat by text or microphone. In call mode you talk and it answers out loud.
- Search the web, read pages, run code, create files and open programs. It asks before anything risky.
- Write programs. Turn on the Code button and an agent edits files in a project folder, runs commands and checks web pages in a hidden browser. Every change can be undone. Commands that download, install or delete something ask first, unless you pick the no-questions mode.
- Make PowerPoint presentations.
- Generate pictures and short videos through ComfyUI, if you have it.
- Remember facts between chats. You can see and delete all of them.
- Use other models: Ollama, LM Studio, OpenAI, Gemini, OpenRouter, Anthropic or any OpenAI compatible server. MCP servers and custom skills work too.

The interface is in English and Russian, with light and dark themes.

<table>
<tr>
<td width="50%"><img src="docs/images/tools.png" alt="The model searching the web"><br><sub>The model searches the web by itself</sub></td>
<td width="50%"><img src="docs/images/models.png" alt="Model settings with a memory and speed estimate"><br><sub>How much memory a model needs and how fast it runs</sub></td>
</tr>
<tr>
<td><img src="docs/images/voice.png" alt="Voice settings"><br><sub>What it hears and sees during a call</sub></td>
<td><img src="docs/images/settings.png" alt="Language and theme settings"><br><sub>Languages and themes</sub></td>
</tr>
</table>

## How to install

1. Download `PIVEN-Companion-<version>-Setup.exe` from [Releases](https://github.com/covriknapoly-glitch/piven-companion/releases).
2. Run it. Administrator rights are not needed.
3. Open PIVEN Companion from the Start menu.

Python, llama.cpp and all libraries are already inside. Models are not: you pick them yourself in the app.

You will need:

- Windows 10 or 11, 64 bit.
- Preferably an NVIDIA graphics card. Without one it works on the processor, just slower.
- About 1.2 GB for the program plus space for models (usually 2 to 20 GB each).

## First launch

The app will suggest a model that fits your graphics card. Download it and say hello. Everything else (voice, memory, pictures, cloud models) is turned on in Settings when you want it.

## About your data

- Chats, settings and memory are stored in `%LOCALAPPDATA%\PIVEN`.
- Nothing is downloaded without your OK. You always see the size and license first.
- Messages go to the cloud only if you add a cloud provider yourself. Keys are encrypted by Windows.
- With a cloud model, screenshots and transcribed speech from a call go to that service too. Computer sound includes other people on a call, so let them know.
- Use voice cloning only with your own voice or the voice of someone who has agreed to it.
- Generated pictures and videos carry a machine-readable AI mark (IPTC `trainedAlgorithmicMedia`).

## For developers

To run from source:

1. Put Python 3.11 x64 in `runtime\Python311`.
2. Install the libraries:
   ```
   runtime\Python311\python.exe -m pip install --target .packages -r requirements.txt
   ```
3. Put llama.cpp in `llama.cpp\bin`.
4. Run `Запустить PIVEN.cmd`.

After changing the interface in `ui/src`, rebuild it with `ui\scripts\build.cmd` (run `npm install` in `ui` once before that).

Tests:

```
runtime\Python311\python.exe -m unittest discover -s tests
```

The installer is built with [Inno Setup](https://jrsoftware.org/isinfo.php) from `installer\piven.iss`.

What is where:

```
app/chat       chats and memory
app/models     local models, downloads, cloud and other integrations
app/voice      speech and voice installation
app/tools      everything the model can do: files, presentations, browser, MCP
app/window     the window itself
ui             the interface
voice-engines  voice model servers
skills         instructions for the model
tests          tests
installer      installer script
```

Models and voice engines are not kept in the repository.

## Terms of use

You choose the models, voices and services, and you are responsible for what you create and how you use it. The author is not connected with them. Read [TERMS.txt](TERMS.txt).

## License

GPL v3 or later. Use it, change it, share it for free. If you share a changed version, it has to stay open too. Other people's components and their licenses are listed in [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md).

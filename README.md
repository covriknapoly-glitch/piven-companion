<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
  <img src="docs/images/logo-light.svg" alt="PIVEN logo" width="120">
</picture>

# PIVEN Companion

An AI companion that lives on your own computer. No subscription, and your chats stay with you.

[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)
![Windows 10/11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)
![llama.cpp](https://img.shields.io/badge/runs%20on-llama.cpp-8A2BE2)

<img src="docs/images/main-window.svg" alt="PIVEN Companion main window" width="900">

</div>

## What it is

I wanted a chat with a neural network that works without the internet, does not send my messages anywhere and can do more than just talk. So here it is.

You download a model right in the app, and it runs on your graphics card through llama.cpp. Before downloading, the app tells you honestly whether the model fits in your memory and how fast it will be.

## What it can do

- **Talk.** Type or speak into the microphone. There is a call mode where you just talk and it answers out loud.
- **Do things on the computer.** Search the web, read pages, run code to check itself, create files and whole projects, open programs and sites. Before anything risky it asks you first.
- **Make presentations.** Ask for one and you get a PowerPoint file.
- **Draw.** Pictures and short videos go through ComfyUI, if you have it.
- **Remember.** It keeps important facts between chats. You can see and delete everything it remembers.
- **Work with other models.** Ollama, LM Studio, OpenAI, Gemini, OpenRouter, Anthropic and any OpenAI compatible server. MCP servers and your own skills are supported too.
- **Help on stream.** It can read Twitch chat and run polls.

The interface is in English, Russian, Chinese and Spanish, with light and dark themes.

<table>
<tr>
<td width="50%"><img src="docs/images/models.svg" alt="Downloading a model"><br><sub>Picking a model</sub></td>
<td width="50%"><img src="docs/images/tools.svg" alt="The model using tools"><br><sub>The model searches and runs code by itself</sub></td>
</tr>
<tr>
<td><img src="docs/images/voice.svg" alt="Voice settings"><br><sub>Voice</sub></td>
<td><img src="docs/images/settings.svg" alt="Settings"><br><sub>Settings</sub></td>
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

The app will suggest a model that fits your graphics card. Download it and say hello. Everything else (voice, memory, pictures, cloud models, Twitch) is turned on in Settings when you want it.

## About your data

- Chats, settings and memory are stored in `%LOCALAPPDATA%\OllamaCompanion` and do not go anywhere.
- Nothing is downloaded without your OK. You always see the size and license first.
- Messages go to the cloud only if you add a cloud provider yourself. Keys are encrypted by Windows.

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
app/tools      everything the model can do: files, presentations, browser, MCP, Twitch
app/window     the window itself
ui             the interface
voice-engines  voice model servers
skills         instructions for the model
tests          tests
installer      installer script
```

Models and voice engines are not kept in the repository.

## License

GPL v3 or later. Use it, change it, share it for free. If you share a changed version, it has to stay open too. Other people's components and their licenses are listed in [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md).

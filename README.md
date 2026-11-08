<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
  <img src="docs/images/logo-light.svg" alt="PIVEN logo" width="120">
</picture>

# PIVEN Companion

ai agent for Windows that runs on your own pc.

[![License: GPL v3](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)
![Windows 10/11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)

<img src="docs/images/main-window.png" alt="PIVEN main window" width="900">

</div>

## what is this

i wanted an ai agent that works without internet and keeps my stuff on my pc, so i made one.

you download a model right in the app and talk to it. before downloading it tells you if the model will fit and how fast it will be.

## what it can do

- chat by text or voice. you can also just call it and talk.
- search the internet, open programs and make files.
- write programs for you. it works in its own folder and you can undo what it did.
- make presentations.
- draw pictures and short videos if you have ComfyUI.
- remember stuff between chats. you can see and delete everything it remembers.
- work with Ollama, LM Studio, OpenAI, Claude, Gemini and OpenRouter if you want.

english and russian. light and dark themes.

<table>
<tr>
<td width="50%"><img src="docs/images/tools.png" alt="the agent writing a program"><br><sub>writes programs</sub></td>
<td width="50%"><img src="docs/images/models.png" alt="model settings"><br><sub>shows if a model fits</sub></td>
</tr>
<tr>
<td><img src="docs/images/voice.png" alt="voice settings"><br><sub>voice and calls</sub></td>
<td><img src="docs/images/settings.png" alt="language and themes"><br><sub>themes</sub></td>
</tr>
</table>

## how to install

1. download `PIVEN-Companion-<version>-Setup.exe` from [releases](https://github.com/covriknapoly-glitch/piven-companion/releases).
2. run it.
3. open PIVEN Companion from the start menu.

you need:

- Windows 10 or 11
- an NVIDIA card is best. without one it still works but slower.
- about 1.2 GB for the app and more for models (usually 2 to 20 GB each)

when you open it, it suggests a model for your pc. download it and say hi.

## your data

- everything stays on your pc in `%LOCALAPPDATA%\PIVEN`.
- nothing downloads unless you say so.
- if you use a cloud model, your messages go to that service. on a call that includes screenshots and what it hears, so tell people if you're on a call with them.
- only copy your own voice or the voice of someone who said it's ok.
- pictures and videos made in the app have a hidden mark that says ai made them.

## if you want to build it

1. put Python 3.11 in `runtime\Python311`.
2. run `runtime\Python311\python.exe -m pip install --target .packages -r requirements.txt`
3. put llama.cpp in `llama.cpp\bin`.
4. run `Запустить PIVEN.cmd`.

if you change the interface, run `npm install` in `ui` once and then `ui\scripts\build.cmd`.

## rules

you pick the models, voices and services, and what you do with them is on you. i don't make them and i'm not connected to them. see [TERMS.txt](TERMS.txt).

## license

GPL v3 or later. it's free. if you share a changed version it has to stay open too. other people's stuff and its licenses are in [docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md).

# Сторонние компоненты и их лицензии

Сама программа распространяется по GNU GPL версии 3 или более поздней (`LICENSE`, `NOTICE`): её и любые изменённые версии можно распространять только под той же лицензией и с открытым исходным кодом. Сторонние компоненты ниже остаются под своими лицензиями; все они совместимы с GPL-3.0.

PIVEN Companion использует и распространяет вместе с собой следующие компоненты. Тексты лицензий лежат в `docs/licenses`, рядом со шрифтами (`*-OFL.txt`) и внутри папок пакетов (`*.dist-info`).

## В репозитории и в сборке интерфейса

| Компонент | Лицензия | Где |
|---|---|---|
| React, React DOM, Scheduler (Meta Platforms) | MIT | встроены в `ui/dist/app.js`; `docs/licenses/react*-MIT.txt`, `scheduler-MIT.txt` |
| Symbols Nerd Font (Nerd Fonts) | MIT; значки внутри: Codicons (Microsoft) — CC BY 4.0, Material Design Icons — Apache 2.0, Font Awesome — CC BY 4.0 | иконки интерфейса, подмножество `ui/src/assets/fonts/SymbolsNerdFont-Icons.ttf`; `SymbolsNerdFont-MIT.txt` рядом |
| Lack (Adrien Midzic, Velvetyne), Martian Grotesk Wide (Evil Martians), Cascadia Code (Microsoft), Smiley Sans / 得意黑 (atelierAnchor, без изменений, для китайского интерфейса) | SIL Open Font License 1.1 | `ui/src/assets/fonts` (тексты `*-OFL.txt` рядом) |

## В установщике (не в репозитории)

| Компонент | Лицензия |
|---|---|
| CPython 3.11 | PSF License (`runtime/Python311/LICENSE.txt`) |
| llama.cpp / ggml | MIT (`docs/licenses/llama.cpp-MIT.txt`) |
| LLVM OpenMP (`libomp.dll`, из сборки llama.cpp) | Apache 2.0 with LLVM Exceptions (`llama.cpp/bin/LICENSE-LLVM-OpenMP`) |
| NVIDIA CUDA Runtime, cuBLAS (`cudart64_13.dll`, `cublas64_13.dll`, `cublasLt64_13.dll`) | NVIDIA CUDA Toolkit EULA — распространяемые компоненты (Attachment A) |
| pywebview | BSD-3-Clause |
| pythonnet, clr_loader | MIT |
| bottle, proxy_tools | MIT |
| Pillow | MIT-CMU |
| NumPy | BSD-3-Clause (и включённые части под 0BSD, MIT, Zlib, CC0) |
| lxml | BSD-3-Clause |
| python-pptx | MIT |
| XlsxWriter | BSD-2-Clause |
| SoundCard | BSD-3-Clause |
| cffi | MIT-0 |
| pycparser | BSD-3-Clause |
| typing_extensions | PSF-2.0 |

## Что программа скачивает по просьбе пользователя

Модели нейросетей, голосовые движки (PyTorch, Transformers и другие пакеты из PyPI), ComfyUI и его модели не входят в программу. Они скачиваются только по кнопке, и у каждой модели перед скачиванием видна её лицензия; некоммерческие помечены отдельно. Пользователь сам отвечает за соблюдение лицензий скачанных моделей.

Модели, которые программа предлагает сама: Qwen3-Embedding-0.6B (память, Apache 2.0) и рекомендуемая первая модель чата — у неё своя лицензия, показанная на странице модели. Видео и картинки рисуются через workflow ComfyUI, который выбирает пользователь.

## Логотип

Логотип PIVEN (`assets/piven_logo.svg` и производные `piven.ico`, `piven_icon_256.png`) принадлежит автору программы.

# PIVEN Companion · веб-интерфейс

React + TypeScript интерфейс, который открывается в окне `web_companion.pyw` (pywebview + WebView2) и работает поверх движка `companion_core.py`. Перенесён из `Архив/PIVEN Companion Modern/modern-ui`; вместо отдельного Ollama-моста и `localStorage` он теперь читает и пишет настоящие чаты и настройки Компаньона.

## Устройство

- `src/App.tsx` — каркас: боковая панель с поиском и чатами, выбор модели, окно настроек, поле ввода с подсказкой режима, светлая/тёмная тема (выбор хранится в `localStorage` окна).
- `src/board.tsx` — рабочая доска: перемещение мышью и колёсиком, масштаб Ctrl+колёсико, перетаскивание карточек за заголовок (позиции хранятся по чатам в `localStorage`), стрелки между карточками, «показать всё» и «к последнему».
- `src/markdown.tsx` — безопасный Markdown для ответов (React-элементы, без HTML): заголовки, списки, таблицы, цитаты, блоки кода с копированием.
- `src/assets/piven_logo.png` — логотип PIVEN, уменьшенная копия `assets/piven_logo_flat.png`.

## Сборка

```
scripts\build.cmd
```

Собирает `src/` в `dist/` вложенным `node_modules\@esbuild\win32-x64\esbuild.exe` — Node.js не нужен. Проверки типов при этой сборке нет; для неё понадобятся Node.js и `tsc`.

## Как страница говорит с Python

`src/bridge.ts` описывает `window.pywebview.api` — методы класса `WebApi` в `web_companion.pyw`. Страница раз в секунду (во время ответа — чаще) вызывает `poll(version)` и получает снимок состояния только при изменениях. Команды: `send`, `select_chat`, `new_chat`, `set_model`, `set_speech`, `interrupt`, `refresh_models`, `image_data`, `open_file`, `copy_text`.

## Что ещё не перенесено

Вложения, микрофон и звук компьютера, наблюдение за экраном, подтверждение скачивания, Twitch и полное окно настроек остаются в обычном окне Компаньона.

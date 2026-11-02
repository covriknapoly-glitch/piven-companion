# ui

Интерфейс программы: React и TypeScript. Открывается в окне `app/window/main.pyw`.

- `src/` — исходники, `dist/` — сборка, которую загружает окно.
- `src/bridge.ts` — какие методы Python страница может вызвать (класс `WebApi` в `main.pyw`).
- `src/i18n/strings.json` — переводы на английский, китайский и испанский.

Собрать после правок:

```
scripts\build.cmd
```

import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { isPhone, isUnchanged, waitForEngine, type ChatSummary, type EngineState, type SearchHit, type WebApi } from "./bridge";
import { Lightbox } from "./cards";
import { Composer } from "./composer";
import { CommandDialog, ConfirmDialog, DownloadDialog, HubDialog, SearchDialog } from "./dialogs";
import { VoiceHubDialog } from "./voicehub";
import { Icon } from "./icons";
import { CallPanel } from "./call";
import { ContextRing } from "./context";
import { LinkContext } from "./markdown";
import { SettingsDialog, FONT_CHOICES, prefetchSettings, type FontChoice } from "./settings";
import { HelpDialog, type SlashCommand } from "./commands";
import { translate } from "./i18n";
import { Sidebar, type ChatActions } from "./sidebar";
import { Transcript } from "./transcript";
import { Decor, IconButton, shortModel, thinkingName } from "./ui";
import { THEME_IDS, THEMES, isLightTheme, type ThemeId } from "./themes";
import { Workspace, type WorkspaceTab } from "./workspace";
import { phoneHost } from "./linkhost";
import { PhoneBanner, PhoneStart } from "./pairing";
import { UpdateBanner } from "./update";
import { LANGUAGES, defaultLanguage, setLanguage, type Language } from "./i18n";

const THEME_KEY = "piven-ui-theme";
const BROWSER_KEY = "piven-browser-open";
const WIDTH_KEY = "piven-workspace-width";
const FONT_KEY = "piven-font";
const LANGUAGE_KEY = "piven-language";

function readStored(key: string, allowed: string[], fallback: string) {
  try {
    const saved = localStorage.getItem(key);
    if (saved && allowed.includes(saved)) return saved;
  } catch {  }
  return fallback;
}
function writeStored(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch {  }
}

function trackDockHeight(dock: HTMLDivElement | null) {
  if (!dock?.parentElement) return;
  const area = dock.parentElement;
  const observer = new ResizeObserver(() => area.style.setProperty("--dock-h", `${dock.offsetHeight}px`));
  observer.observe(dock);
  return () => observer.disconnect();
}

function useTheme() {
  const [choice, setChoice] = useState<ThemeId>(() => readStored(THEME_KEY, THEME_IDS, "system") as ThemeId);
  const [resolved, setResolved] = useState<"light" | "dark">("dark");
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const apply = () => {
      const next = choice === "system" ? (media.matches ? "light" : "dark") : choice;
      document.documentElement.dataset.theme = next;
      setResolved(isLightTheme(next) ? "light" : "dark");
    };
    apply();
    media.addEventListener("change", apply);
    try { localStorage.setItem(THEME_KEY, choice); } catch {  }
    return () => media.removeEventListener("change", apply);
  }, [choice]);
  return [choice, setChoice, resolved] as const;
}

export default function App() {
  const [api, setApi] = useState<WebApi | null>(null);
  const [engineMissing, setEngineMissing] = useState(false);
  const [state, setState] = useState<EngineState | null>(null);
  const [toast, setToast] = useState<{ text: string; kind: "info" | "error" } | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 900);
  const [dialog, setDialog] = useState<"" | "settings" | "search" | "hub" | "voice-asr" | "voice-tts" | "help">("");
  const [deleting, setDeleting] = useState<ChatSummary | null>(null);
  const [lightbox, setLightbox] = useState("");
  const [focusIndex, setFocusIndex] = useState<{ index: number; nonce: number } | null>(null);
  const [browserOpen, setBrowserOpen] = useState(() => readStored(BROWSER_KEY, ["1", "0"], "0") === "1");

  const [workspaceMounted, setWorkspaceMounted] = useState(browserOpen);
  useEffect(() => {
    if (browserOpen) { setWorkspaceMounted(true); return; }
    const timer = window.setTimeout(() => setWorkspaceMounted(false), 260);
    return () => window.clearTimeout(timer);
  }, [browserOpen]);
  const workspaceClosing = workspaceMounted && !browserOpen && !state?.listening.running;

  const [workspaceWidth, setWorkspaceWidth] = useState(() => { try { return Number(localStorage.getItem(WIDTH_KEY)) || 0; } catch { return 0; } });
  const [resizing, setResizing] = useState(false);
  useEffect(() => { writeStored(WIDTH_KEY, String(Math.round(workspaceWidth))); }, [workspaceWidth]);
  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    setResizing(true);
    document.body.classList.add("resizing");
    const move = (moveEvent: PointerEvent) => {
      const max = Math.max(320, window.innerWidth - (sidebarOpen ? 260 : 0) - 380);
      setWorkspaceWidth(Math.min(max, Math.max(320, window.innerWidth - moveEvent.clientX)));
    };
    const stop = () => {
      setResizing(false);
      document.body.classList.remove("resizing");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  };
  const [browserRequest, setBrowserRequest] = useState<{ url: string; nonce: number } | null>(null);
  useEffect(() => { writeStored(BROWSER_KEY, browserOpen ? "1" : "0"); }, [browserOpen]);
  const [language, setLanguageChoice] = useState<Language>(() => readStored(LANGUAGE_KEY, LANGUAGES.map(([value]) => value), defaultLanguage()) as Language);
  useEffect(() => { writeStored(LANGUAGE_KEY, language); setLanguage(language); if (api) void api.set_language(language); }, [language, api]);
  const [fontChoice, setFontChoice] = useState<FontChoice>(() => readStored(FONT_KEY, FONT_CHOICES.map(([value]) => value), FONT_CHOICES[0][0]) as FontChoice);
  useEffect(() => { writeStored(FONT_KEY, fontChoice); document.documentElement.dataset.font = fontChoice; }, [fontChoice]);
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("browser");
  const openLink = useCallback((url: string) => { if (isPhone) { window.open(url, "_blank", "noopener"); return; } setBrowserOpen(true); setWorkspaceTab("browser"); setBrowserRequest({ url, nonce: Date.now() }); }, []);

  const modelBrowse = state?.browserRequest?.nonce;
  useEffect(() => { if (modelBrowse && state?.browserRequest) openLink(state.browserRequest.url); }, [modelBrowse]);
  const [pendingFocus, setPendingFocus] = useState<SearchHit | null>(null);
  const [prefill, setPrefill] = useState<{ text: string; nonce: number } | null>(null);
  const [theme, setTheme, resolvedTheme] = useTheme();
  const versionRef = useRef(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const engineReady = useCallback((engine: WebApi) => {
    setApi(engine);
    void engine.state().then((snapshot) => { versionRef.current = snapshot.version; setState(snapshot); });
  }, []);
  useEffect(() => { if (api && !isPhone) phoneHost.start(api); }, [api]);
  useEffect(() => {
    if (isPhone) return;
    void waitForEngine().then((engine) => {
      if (!engine) { setEngineMissing(true); return; }
      setApi(engine);
      void engine.state().then((snapshot) => { versionRef.current = snapshot.version; setState(snapshot); });
    });
  }, []);
  useEffect(() => {
    if (!api) return;
    const style = getComputedStyle(document.documentElement);
    void api.set_title_theme(style.getPropertyValue("--panel"), style.getPropertyValue("--text"), resolvedTheme === "dark");
  }, [api, theme, resolvedTheme]);

  const poll = useCallback(async () => {
    if (!api) return;
    const result = await api.poll(versionRef.current);
    if (isUnchanged(result)) return;
    versionRef.current = result.version;
    setState(result);
  }, [api]);
  useEffect(() => {
    if (!api) return;
    const timer = window.setInterval(() => { void poll(); }, state?.busy || state?.listening.running ? 300 : 900);
    return () => window.clearInterval(timer);
  }, [api, poll, state?.busy, state?.listening.running]);

  const notify = useCallback((text?: string, kind: "info" | "error" = "error") => { if (text) setToast({ text, kind }); }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), toast.kind === "error" ? 5200 : 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);
  useEffect(() => { if (state?.notice) notify(state.notice); }, [state?.notice, notify]);

  const done = useCallback((error?: string) => { notify(error); void poll(); }, [notify, poll]);
  const openHit = useCallback((hit: SearchHit) => {
    if (!api || !state) return;
    if (hit.chatId === state.activeChatId) { setFocusIndex({ index: hit.index, nonce: Date.now() }); return; }
    setPendingFocus(hit);
    void api.select_chat(hit.chatId).then((result) => done(result.ok ? undefined : result.error));
  }, [api, done, state?.activeChatId]);
  const copy = useCallback((text: string) => { if (api) void api.copy_text(text).then(() => notify("Скопировано", "info")); }, [api, notify]);
  const newChat = useCallback(() => { if (api) void api.new_chat().then((result) => { done(result.ok ? undefined : result.error); inputRef.current?.focus(); }); }, [api, done]);
  const stop = useCallback(() => { if (api) void api.interrupt().then(() => done()); }, [api, done]);

  useEffect(() => {
    if (pendingFocus && state?.activeChatId === pendingFocus.chatId) {
      setFocusIndex({ index: pendingFocus.index, nonce: Date.now() });
      setPendingFocus(null);
    }
  }, [pendingFocus, state?.activeChatId]);

  const actions: ChatActions | null = useMemo(() => api && {
    select: (chat) => { if (window.innerWidth <= 900) setSidebarOpen(false); if (chat.id !== state?.activeChatId) void api.select_chat(chat.id).then((result) => done(result.ok ? undefined : result.error)); },
    rename: (chat, title) => { void api.rename_chat(chat.id, title).then((result) => done(result.ok ? undefined : result.error)); },
    pin: (chat) => { void api.pin_chat(chat.id, !chat.pinned).then(() => done()); },
    exportChat: (chat, markdown) => { void api.export_chat(chat.id, markdown).then((result) => { if (result.ok) notify(`Сохранено: ${result.path}`, "info"); else if (!result.cancelled) notify(result.error); }); },
    remove: (chat) => setDeleting(chat),
    project: (chat, action) => {
      void api.select_chat(chat.id)
        .then(() => (action === "folder" ? api.code_pick_folder() : api.code_open_folder()))
        .then((result) => done(result.ok || result.cancelled ? undefined : result.error));
    },
    moveToProjects: (chat) => { void api.chat_kind(chat.id, !chat.code).then((result) => done(result.ok ? undefined : result.error)); },
  }, [api, state?.activeChatId, done, notify]);

  const stateRef = useRef(state);
  stateRef.current = state;
  const [searchPreset, setSearchPreset] = useState<{ text: string; nonce: number } | null>(null);
  const prefetched = useRef(false);
  useEffect(() => {
    if (!api || !state || prefetched.current) return;
    prefetched.current = true;
    window.setTimeout(() => prefetchSettings(api, state.settings.model), 2500);
  }, [api, state]);

  const chatOrder = useCallback(() => {
    const current = stateRef.current;
    if (!current) return [];
    const kind = current.chats.filter((chat) => Boolean(chat.code) === current.code.on);
    const byDate = (a: ChatSummary, b: ChatSummary) => (b.updated || 0) - (a.updated || 0);
    return [...kind.filter((chat) => chat.pinned).sort(byDate), ...kind.filter((chat) => !chat.pinned).sort(byDate)];
  }, []);
  const lastAnswer = useCallback(() => {
    const items = stateRef.current?.items ?? [];
    return [...items].reverse().find((item) => item.role === "assistant" && item.text.trim())?.text ?? "";
  }, []);
  const newProject = useCallback(() => {
    if (!api) return;
    void (stateRef.current?.code.on ? Promise.resolve({ ok: true } as { ok: boolean; error?: string }) : api.code_mode(true)).then((result) => { if (result.ok) newChat(); else done(result.error); });
  }, [api, newChat, done]);

  const commands: SlashCommand[] = useMemo(() => {
    if (!api || !actions) return [];
    const chat = () => stateRef.current?.chats.find((item) => item.id === stateRef.current?.activeChatId);
    const needArg = (arg: string, what: string) => { if (!arg) notify(`Напиши ${what} после команды`); return Boolean(arg); };
    const reply = (result: { ok: boolean; error?: string }) => done(result.ok ? undefined : result.error);
    return [
      { name: "new", hint: "Новый чат", run: () => newChat() },
      { name: "project", hint: "Новый проект", run: () => newProject() },
      { name: "model", args: "название", hint: "Сменить модель", run: (arg) => {
        const models = stateRef.current?.models ?? [];
        const needle = arg.toLowerCase();
        const found = models.find((name) => name.toLowerCase() === needle) ?? models.find((name) => shortModel(name).toLowerCase().includes(needle) || name.toLowerCase().includes(needle));
        if (!arg) { window.dispatchEvent(new Event("piven:model-menu")); return; }
        if (!found) { notify(`Модель «${arg}» не найдена`); return; }
        void api.set_model(found).then(reply);
      } },
      { name: "think", args: "уровень", hint: "Размышление: выкл, низкий, средний, высокий…", run: (arg) => {
        const model = stateRef.current?.settings.model ?? "";
        void api.thinking_options(model).then((options) => {
          if (!options.values.length) { notify("Эта модель не даёт выбрать размышление"); return; }
          const needle = arg.toLowerCase();
          const off = /^(выкл|нет|без|off|no|none)/.test(needle), on = /^(вкл|да|on|yes)/.test(needle);
          const label = (value: unknown) => (value === true ? "с размышлением" : value === false ? "без размышления" : thinkingName(value as never).toLowerCase());
          const value = options.values.find((item) => (off && (item === false || item === "none")) || (on && item === true)
            || String(item).toLowerCase() === needle || (needle && (label(item).startsWith(needle) || (translate(label(item)) ?? "").toLowerCase().startsWith(needle))));
          if (value === undefined) { notify(`Можно: ${options.values.map((item) => label(item)).join(", ")}`); return; }
          void api.set_thinking(model, value).then(reply);
        });
      } },
      { name: "search", args: "текст", hint: "Найти в чатах и сообщениях", run: (arg) => { setSidebarOpen(true); setSearchPreset({ text: arg, nonce: Date.now() }); window.setTimeout(() => searchRef.current?.focus(), 0); } },
      { name: "web", args: "запрос", hint: "Найти в интернете во встроенном браузере", run: (arg) => {
        if (!arg) { setBrowserOpen(true); return; }
        openLink(`https://search.brave.com/search?q=${encodeURIComponent(arg)}`);
      } },
      { name: "image", args: "описание", hint: "Нарисовать картинку", run: (arg) => { if (needArg(arg, "что нарисовать")) void api.send_message(`${language === "en" ? "Draw" : "Нарисуй"} ${arg}`, []).then(reply); } },
      { name: "rename", args: "название", hint: "Переименовать чат", run: (arg) => { const current = chat(); if (current && needArg(arg, "новое название")) actions.rename(current, arg); } },
      { name: "pin", hint: "Закрепить или открепить чат", run: () => { const current = chat(); if (current) actions.pin(current); } },
      { name: "export", hint: "Сохранить чат в файл Markdown", run: () => { const current = chat(); if (current) actions.exportChat(current, true); } },
      { name: "delete", hint: "Удалить чат", run: () => { const current = chat(); if (current) actions.remove(current); } },
      { name: "copy", hint: "Скопировать последний ответ", run: () => { const text = lastAnswer(); if (text) copy(text); else notify("Ответов пока нет"); } },
      { name: "theme", args: "название", hint: "Сменить тему оформления", run: (arg) => {
        const needle = arg.toLowerCase();
        const found = THEMES.find(([id, label]) => id === needle || label.toLowerCase().startsWith(needle) || (translate(label) ?? "").toLowerCase().startsWith(needle));
        if (!arg || !found) { notify(`Темы: ${THEMES.map(([, label]) => label).join(", ")}`); return; }
        setTheme(found[0]);
      } },
      { name: "browser", hint: "Показать или скрыть браузер", run: () => setBrowserOpen((open) => !open) },
      { name: "settings", hint: "Открыть настройки", run: () => setDialog("settings") },
      { name: "stop", hint: "Остановить ответ", run: () => stop() },
      { name: "help", hint: "Все команды и сочетания клавиш", run: () => setDialog("help") },
    ];
  }, [api, actions, newChat, newProject, notify, done, openLink, copy, lastAnswer, setTheme, stop, language]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.ctrlKey || event.metaKey;

      const key = event.code.startsWith("Key") ? event.code.slice(3).toLowerCase() : event.key.toLowerCase();
      if (mod && event.shiftKey && key === "f") { event.preventDefault(); setSidebarOpen(true); window.setTimeout(() => searchRef.current?.focus(), 0); }
      else if (mod && key === "k") { event.preventDefault(); setSidebarOpen(true); window.setTimeout(() => searchRef.current?.focus(), 0); }
      else if (mod && event.shiftKey && key === "n") { event.preventDefault(); newProject(); }
      else if (mod && event.shiftKey && key === "c") { event.preventDefault(); const text = lastAnswer(); if (text) copy(text); }
      else if (mod && key === "n") { event.preventDefault(); newChat(); }
      else if (mod && key === "l") { event.preventDefault(); inputRef.current?.focus(); }
      else if (mod && key === "m") { event.preventDefault(); window.dispatchEvent(new Event("piven:model-menu")); }
      else if (mod && (event.code === "Slash" || event.key === "/")) { event.preventDefault(); setDialog((open) => (open === "help" ? "" : "help")); }
      else if (event.altKey && !mod && (event.key === "ArrowUp" || event.key === "ArrowDown") && api) {
        event.preventDefault();
        const order = chatOrder();
        const at = order.findIndex((chat) => chat.id === stateRef.current?.activeChatId);
        const next = order[at + (event.key === "ArrowUp" ? -1 : 1)];
        if (next) void api.select_chat(next.id).then((result) => done(result.ok ? undefined : result.error));
      }
      else if (mod && (event.code === "Comma" || event.key === ",")) { event.preventDefault(); setDialog("settings"); }
      else if (mod && key === "b") { event.preventDefault(); setSidebarOpen((open) => !open); }
      else if (mod && key === "d") { event.preventDefault(); setBrowserOpen((open) => !open); }
      else if (event.key === "Escape" && state?.busy && !dialog && !lightbox && !deleting) stop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newChat, newProject, stop, copy, lastAnswer, chatOrder, api, done, state?.busy, dialog, lightbox, deleting]);

  if (isPhone && !api) return <PhoneStart onReady={engineReady} />;
  if (engineMissing) {
    return <div className="splash"><Decor corner="br" /><h2>Нет связи с движком</h2><p>Этот интерфейс открывается файлом «Запустить веб-интерфейс» в папке программы.</p></div>;
  }
  if (!api || !state || !actions) {
    return <div className="splash"><Decor corner="br" /></div>;
  }

  return (
    <LinkContext.Provider value={openLink}>
    <div className={`app ${sidebarOpen ? "" : "sidebar-hidden"}`}>
      <Sidebar api={api} state={state} actions={actions} searchRef={searchRef} onNewChat={newChat}
        onOpenHit={openHit} searchPreset={searchPreset} onSettings={() => setDialog("settings")} onHide={() => setSidebarOpen(false)} />
      {sidebarOpen && <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />}

      <main className="main">
        {!sidebarOpen && <div className="main-corner">
          <IconButton icon="sidebarOpen" label="Показать панель (Ctrl+B)" onClick={() => setSidebarOpen(true)} />
          <IconButton icon="compose" label="Новый чат (Ctrl+N)" onClick={newChat} />
        </div>}
        {!isPhone && !browserOpen && !state.listening.running && <div className="main-corner main-corner-right">
          <IconButton icon="workspaceOff" label="Браузер и файлы (Ctrl+D)" onClick={() => setBrowserOpen(true)} />
        </div>}

        <div className={`chat-tools ${!isPhone && !browserOpen && !state.listening.running ? "beside-corner" : ""}`}>
          <button type="button" className={`code-toggle ${state.code.on ? "on" : ""}`} aria-pressed={state.code.on}
            title={state.code.on ? "Режим кода включён: слева проекты, агент сам пишет файлы и запускает команды. Нажми, чтобы вернуться к чатам" : "Включить режим кода: слева будут проекты, агент сам пишет файлы и запускает команды"}
            onClick={() => { void api.code_mode(!state.code.on).then((result) => done(result.ok ? undefined : result.error)); }}>
            <Icon name="code" size={15} /><span>Код</span>
          </button>
          <ContextRing api={api} state={state} onOpen={() => { if (isPhone) return; setWorkspaceTab("context"); setBrowserOpen(true); }} />
        </div>

        {state.busy && <div className="activity-strip"><i /></div>}
        {isPhone && <PhoneBanner />}
        <UpdateBanner api={api} state={state} onError={done} />

        <Transcript api={api} state={state} focusIndex={focusIndex}
              onCopy={copy} onView={setLightbox} onStop={stop}
              onRetry={() => { void api.retry_last().then((result) => done(result.ok ? undefined : result.error)); }}
              onEdit={(index, text) => { void api.edit_message(index, text).then((result) => done(result.ok ? undefined : result.error)); }}
              onPrefill={(text) => setPrefill({ text, nonce: Date.now() })} onNotice={done} />

        <div className="composer-dock" ref={trackDockHeight}>
          <Composer api={api} state={state} inputRef={inputRef} prefill={prefill} commands={commands} onStop={stop} onError={done} onOpenHub={() => setDialog("hub")} onOpenVoiceHub={(kind = "tts") => setDialog(`voice-${kind}`)}
            onSent={(queued) => { if (queued) notify("Отправится после текущего ответа", "info"); void poll(); }} />
        </div>
      </main>

      {!isPhone && (workspaceMounted || state.listening.running) && (
        <aside className={`workspace ${state.listening.running ? "in-call" : ""} ${workspaceClosing ? "closing" : ""}`} aria-label={state.listening.running ? "Звонок" : "Рабочая панель"}
          style={workspaceWidth ? { ["--ws-w" as string]: `${workspaceWidth}px` } : undefined}>
          <div className={`workspace-resize ${resizing ? "dragging" : ""}`} role="separator" aria-orientation="vertical" title="Потяни, чтобы изменить ширину; двойной щелчок — по умолчанию"
            onPointerDown={startResize} onDoubleClick={() => setWorkspaceWidth(0)} />
          {state.listening.running && <CallPanel api={api} state={state} onError={done} />}

          {workspaceMounted && <div className={state.listening.running ? "workspace-hidden" : "workspace-slot"}>
            <Workspace api={api} state={state} tab={workspaceTab} setTab={setWorkspaceTab} browserRequest={browserRequest}
              onClose={() => setBrowserOpen(false)} covered={Boolean(dialog || deleting || lightbox || state.confirm || state.listening.running || workspaceClosing)} />
          </div>}
        </aside>
      )}

      {dialog === "settings" && <SettingsDialog state={state} api={api} theme={theme} setTheme={setTheme} fontChoice={fontChoice} setFontChoice={setFontChoice} language={language} setLanguage={setLanguageChoice} onClose={() => setDialog("")}
        onOpenHub={() => setDialog("hub")} onOpenVoiceHub={(kind) => setDialog(`voice-${kind}`)} />}
      {dialog === "search" && <SearchDialog api={api} onClose={() => setDialog("")} onOpen={openHit} />}
      {dialog === "help" && <HelpDialog commands={commands} onClose={() => setDialog("")} />}
      {(dialog === "voice-asr" || dialog === "voice-tts") && <VoiceHubDialog api={api} initialKind={dialog === "voice-asr" ? "asr" : "tts"}
        onClose={() => setDialog("settings")} onDone={() => notify("Голосовая модель скачана", "info")} />}
      {dialog === "hub" && <HubDialog api={api} onClose={() => setDialog("")} onDone={() => { void poll(); notify("Модель скачана", "info"); }} />}
      {deleting && <ConfirmDialog title="Удалить чат?" text={`«${deleting.title}» и вся его история будут удалены. Это нельзя отменить.`} confirmLabel="Удалить" danger
        onClose={() => setDeleting(null)} onConfirm={() => { void api.delete_chat(deleting.id).then((result) => done(result.ok ? undefined : result.error)); }} />}
      {state.confirm?.kind === "download" && <DownloadDialog confirm={state.confirm} api={api} />}
      {state.confirm?.kind === "command" && <CommandDialog confirm={state.confirm} api={api} />}
      {lightbox && <Lightbox api={api} path={lightbox} onClose={() => setLightbox("")} />}
      {toast && <div className={`toast ${toast.kind}`} role="status"><Icon name={toast.kind === "error" ? "alert" : "check"} size={16} />{toast.text}</div>}
    </div>
    </LinkContext.Provider>
  );
}

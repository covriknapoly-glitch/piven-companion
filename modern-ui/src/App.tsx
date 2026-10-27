import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { isUnchanged, waitForEngine, type ChatSummary, type EngineState, type SearchHit, type WebApi } from "./bridge";
import { Board, type BoardCard } from "./board";
import { Lightbox, MessageCard, ROLE_WIDTH, ThinkingCard } from "./cards";
import { Composer } from "./composer";
import { ConfirmDialog, DownloadDialog, HubDialog, SearchDialog, TwitchDialog } from "./dialogs";
import { VoiceHubDialog } from "./voicehub";
import { Icon } from "./icons";
import { BrowserPane } from "./browser";
import { CallPanel } from "./call";
import { LinkContext } from "./markdown";
import { SettingsDialog, FONT_CHOICES, type ThemeChoice, type ViewMode, type FontChoice } from "./settings";
import { Sidebar, type ChatActions } from "./sidebar";
import { Transcript } from "./transcript";
import { IconButton, Logo, MenuButton } from "./ui";

const THEME_KEY = "piven-ui-theme";
const BROWSER_KEY = "piven-browser-open";
const VIEW_KEY = "piven-view-mode";
const FONT_KEY = "piven-font";

function readStored(key: string, allowed: string[], fallback: string) {
  try {
    const saved = localStorage.getItem(key);
    if (saved && allowed.includes(saved)) return saved;
  } catch { /* storage may be unavailable */ }
  return fallback;
}
function writeStored(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* ignore */ }
}

function readTheme(): ThemeChoice {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark" || saved === "system") return saved;
  } catch { /* storage may be unavailable */ }
  return "system";
}

function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>(readTheme);
  const [resolved, setResolved] = useState<"light" | "dark">("dark");
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const apply = () => {
      const next = choice === "system" ? (media.matches ? "light" : "dark") : choice;
      document.documentElement.dataset.theme = next;
      setResolved(next);
    };
    apply();
    media.addEventListener("change", apply);
    try { localStorage.setItem(THEME_KEY, choice); } catch { /* ignore */ }
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
  const [dialog, setDialog] = useState<"" | "settings" | "search" | "twitch" | "hub" | "voice-asr" | "voice-tts">("");
  const [deleting, setDeleting] = useState<ChatSummary | null>(null);
  const [lightbox, setLightbox] = useState("");
  const [focus, setFocus] = useState<{ key: string; nonce: number } | null>(null);
  const [focusIndex, setFocusIndex] = useState<{ index: number; nonce: number } | null>(null);
  const [browserOpen, setBrowserOpen] = useState(() => readStored(BROWSER_KEY, ["1", "0"], "0") === "1");
  const [browserRequest, setBrowserRequest] = useState<{ url: string; nonce: number } | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>(() => readStored(VIEW_KEY, ["chat", "cards"], "chat") as ViewMode);
  useEffect(() => { writeStored(BROWSER_KEY, browserOpen ? "1" : "0"); }, [browserOpen]);
  useEffect(() => { writeStored(VIEW_KEY, viewMode); }, [viewMode]);
  const [fontChoice, setFontChoice] = useState<FontChoice>(() => readStored(FONT_KEY, FONT_CHOICES.map(([value]) => value), "mono") as FontChoice);
  useEffect(() => { writeStored(FONT_KEY, fontChoice); document.documentElement.dataset.font = fontChoice; }, [fontChoice]);
  const openLink = useCallback((url: string) => { setBrowserOpen(true); setBrowserRequest({ url, nonce: Date.now() }); }, []);
  const [pendingFocus, setPendingFocus] = useState<SearchHit | null>(null);
  const [prefill, setPrefill] = useState<{ text: string; nonce: number } | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [theme, setTheme, resolvedTheme] = useTheme();
  const versionRef = useRef(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void waitForEngine().then((engine) => {
      if (!engine) { setEngineMissing(true); return; }
      setApi(engine);
      void engine.state().then((snapshot) => { versionRef.current = snapshot.version; setState(snapshot); });
    });
  }, []);
  useEffect(() => { if (api) void api.set_title_theme(resolvedTheme === "dark"); }, [api, resolvedTheme]);

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
  const copy = useCallback((text: string) => { if (api) void api.copy_text(text).then(() => notify("Скопировано", "info")); }, [api, notify]);
  const newChat = useCallback(() => { if (api) void api.new_chat().then((result) => { done(result.ok ? undefined : result.error); inputRef.current?.focus(); }); }, [api, done]);
  const stop = useCallback(() => { if (api) void api.interrupt().then(() => done()); }, [api, done]);

  // A search hit in another chat: switch first, then focus the card once that chat is on screen.
  useEffect(() => {
    if (pendingFocus && state?.activeChatId === pendingFocus.chatId) {
      setFocus({ key: String(pendingFocus.index), nonce: Date.now() });
      setFocusIndex({ index: pendingFocus.index, nonce: Date.now() });
      setPendingFocus(null);
    }
  }, [pendingFocus, state?.activeChatId]);

  const actions: ChatActions | null = useMemo(() => api && {
    select: (chat) => { if (chat.id !== state?.activeChatId) void api.select_chat(chat.id).then((result) => done(result.ok ? undefined : result.error)); },
    rename: (chat, title) => { void api.rename_chat(chat.id, title).then((result) => done(result.ok ? undefined : result.error)); },
    pin: (chat) => { void api.pin_chat(chat.id, !chat.pinned).then(() => done()); },
    exportChat: (chat, markdown) => { void api.export_chat(chat.id, markdown).then((result) => { if (result.ok) notify(`Сохранено: ${result.path}`, "info"); else if (!result.cancelled) notify(result.error); }); },
    remove: (chat) => setDeleting(chat),
  }, [api, state?.activeChatId, done, notify]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.ctrlKey || event.metaKey;
      const key = event.key.toLowerCase();
      if (mod && event.shiftKey && key === "f") { event.preventDefault(); setDialog("search"); }
      else if (mod && key === "k") { event.preventDefault(); setSidebarOpen(true); window.setTimeout(() => searchRef.current?.focus(), 0); }
      else if (mod && key === "n") { event.preventDefault(); newChat(); }
      else if (mod && event.key === ",") { event.preventDefault(); setDialog("settings"); }
      else if (mod && key === "b") { event.preventDefault(); setSidebarOpen((open) => !open); }
      else if (mod && key === "d") { event.preventDefault(); setBrowserOpen((open) => !open); }
      else if (event.key === "Escape" && state?.busy && !dialog && !lightbox && !deleting) stop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newChat, stop, state?.busy, dialog, lightbox, deleting]);

  if (engineMissing) {
    return <div className="splash"><Logo size={96} /><h2>Нет связи с движком</h2><p>Этот интерфейс открывается файлом «Запустить веб-интерфейс» в папке Компаньона.</p></div>;
  }
  if (!api || !state || !actions) {
    return <div className="splash"><Logo size={96} pulse /><p>Загружаю чаты…</p></div>;
  }

  const model = state.settings.model;
  const lastAssistant = state.items.map((item) => item.role).lastIndexOf("assistant");
  const cards: BoardCard[] = state.items.map((item, index) => ({
    key: String(index), role: item.role, width: ROLE_WIDTH[item.role] ?? 520,
    node: <MessageCard api={api} item={item} model={model} canRetry={index === lastAssistant && !state.busy}
      onCopy={copy} onView={setLightbox} onRetry={() => { void api.retry_last().then((result) => done(result.ok ? undefined : result.error)); }} />,
  }));
  if (state.busy) cards.push({ key: "thinking", role: "thinking", width: ROLE_WIDTH.thinking, node: <ThinkingCard state={state} onStop={stop} /> });
  const empty = !state.items.length && !state.busy;
  const activeChat = state.chats.find((chat) => chat.id === state.activeChatId);
  const recent = state.chats.filter((chat) => chat.id !== state.activeChatId && chat.count > 1).slice(0, 5);
  const messageCount = state.items.filter((item) => item.role !== "system").length;

  return (
    <LinkContext.Provider value={openLink}>
    <div className={`app ${sidebarOpen ? "" : "sidebar-hidden"}`}>
      <Sidebar state={state} actions={actions} searchRef={searchRef} onNewChat={newChat}
        onSearchMessages={() => setDialog("search")} onSettings={() => setDialog("settings")} onHide={() => setSidebarOpen(false)} />

      <main className="main">
        <header className="topbar">
          {!sidebarOpen && <>
            <IconButton icon="sidebarOpen" label="Показать панель (Ctrl+B)" onClick={() => setSidebarOpen(true)} />
            <IconButton icon="compose" label="Новый чат (Ctrl+N)" onClick={newChat} disabled={state.busy} />
          </>}
          <div className="topbar-title">
            {renaming && activeChat
              ? <input className="title-input" autoFocus defaultValue={activeChat.title} maxLength={80}
                  onBlur={(event) => { setRenaming(false); const title = event.target.value.trim(); if (title && title !== activeChat.title) actions.rename(activeChat, title); }}
                  onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); if (event.key === "Escape") setRenaming(false); }} />
              : <h1 title="Щёлкни, чтобы переименовать" onClick={() => { if (activeChat) setRenaming(true); }}>{empty ? "Новый чат" : state.chatTitle}</h1>}
            <span>{empty ? "Пока без сообщений" : `${messageCount} ${messageCount % 10 === 1 && messageCount % 100 !== 11 ? "сообщение" : messageCount % 10 >= 2 && messageCount % 10 <= 4 && (messageCount % 100 < 12 || messageCount % 100 > 14) ? "сообщения" : "сообщений"}`}</span>
          </div>
          <span className="topbar-spacer" />
          <IconButton icon={resolvedTheme === "light" ? "moon" : "sun"} label={resolvedTheme === "light" ? "Тёмная тема" : "Светлая тема"} onClick={() => setTheme(resolvedTheme === "light" ? "dark" : "light")} />
          <IconButton icon={browserOpen ? "sidebar" : "sidebarOpen"} label={browserOpen ? "Скрыть браузер (Ctrl+D)" : "Показать браузер (Ctrl+D)"} active={browserOpen} className="flip" onClick={() => setBrowserOpen((open) => !open)} />
          {activeChat && <MenuButton label="Действия с чатом" items={[
            { icon: "search", label: "Искать в сообщениях", hint: "Ctrl+Shift+F", onClick: () => setDialog("search") },
            { icon: "edit", label: "Переименовать", onClick: () => setRenaming(true) },
            { icon: "pin", label: activeChat.pinned ? "Открепить" : "Закрепить", onClick: () => actions.pin(activeChat) },
            "divider",
            { icon: "share", label: "Экспорт в Markdown", onClick: () => actions.exportChat(activeChat, true) },
            { icon: "file", label: "Экспорт в текст", onClick: () => actions.exportChat(activeChat, false) },
            "divider",
            { icon: "trash", label: "Удалить чат…", danger: true, disabled: state.busy, onClick: () => setDeleting(activeChat) },
          ]} />}
        </header>

        {state.busy && <div className="activity-strip"><i /></div>}

        {viewMode === "cards" && !empty
          ? <Board chatId={state.activeChatId} cards={cards} focus={focus} />
          : <Transcript api={api} state={state} focusIndex={focusIndex} boardOpen={false} recent={recent}
              onCopy={copy} onView={setLightbox} onStop={stop}
              onRetry={() => { void api.retry_last().then((result) => done(result.ok ? undefined : result.error)); }}
              onShowOnBoard={() => undefined}
              onPrefill={(text) => setPrefill({ text, nonce: Date.now() })} onSelectChat={actions.select} />}

        <div className="composer-dock">
          <Composer api={api} state={state} inputRef={inputRef} prefill={prefill} onStop={stop} onError={done} onOpenHub={() => setDialog("hub")} onOpenVoiceHub={() => setDialog("voice-tts")}
            onSent={(queued) => { if (queued) notify("Отправлю после текущего ответа", "info"); void poll(); }} />
        </div>
      </main>

      {(browserOpen || state.listening.running) && (
        <aside className={`workspace ${state.listening.running ? "in-call" : ""}`} aria-label={state.listening.running ? "Звонок" : "Браузер"}>
          {state.listening.running && <CallPanel api={api} state={state} onError={done} />}
          {/* The browser stays mounted under a call so its page survives; its native view is hidden meanwhile. */}
          {browserOpen && <div className={state.listening.running ? "workspace-hidden" : "workspace-slot"}>
            <BrowserPane api={api} openRequest={browserRequest} onClose={() => setBrowserOpen(false)}
              covered={Boolean(dialog || deleting || lightbox || state.confirm || state.listening.running)} />
          </div>}
        </aside>
      )}

      {dialog === "settings" && <SettingsDialog state={state} api={api} theme={theme} setTheme={setTheme} viewMode={viewMode} setViewMode={setViewMode} fontChoice={fontChoice} setFontChoice={setFontChoice} onClose={() => setDialog("")}
        onOpenHub={() => setDialog("hub")} onOpenVoiceHub={(kind) => setDialog(`voice-${kind}`)} onOpenTwitch={() => setDialog("twitch")} />}
      {dialog === "search" && <SearchDialog api={api} onClose={() => setDialog("")} onOpen={(hit) => {
        if (hit.chatId === state.activeChatId) { setFocus({ key: String(hit.index), nonce: Date.now() }); setFocusIndex({ index: hit.index, nonce: Date.now() }); }
        else { setPendingFocus(hit); void api.select_chat(hit.chatId).then((result) => done(result.ok ? undefined : result.error)); }
      }} />}
      {dialog === "twitch" && <TwitchDialog api={api} onClose={() => setDialog("")} />}
      {(dialog === "voice-asr" || dialog === "voice-tts") && <VoiceHubDialog api={api} initialKind={dialog === "voice-asr" ? "asr" : "tts"}
        onClose={() => setDialog("settings")} onDone={() => notify("Голосовая модель скачана", "info")} />}
      {dialog === "hub" && <HubDialog api={api} onClose={() => setDialog("")} onDone={() => { void poll(); notify("Модель скачана", "info"); }} />}
      {deleting && <ConfirmDialog title="Удалить чат?" text={`«${deleting.title}» и вся его история будут удалены. Это нельзя отменить.`} confirmLabel="Удалить" danger
        onClose={() => setDeleting(null)} onConfirm={() => { void api.delete_chat(deleting.id).then((result) => done(result.ok ? undefined : result.error)); }} />}
      {state.confirm && <DownloadDialog confirm={state.confirm} api={api} />}
      {lightbox && <Lightbox api={api} path={lightbox} onClose={() => setLightbox("")} />}
      {toast && <div className={`toast ${toast.kind}`} role="status"><Icon name={toast.kind === "error" ? "alert" : "check"} size={16} />{toast.text}</div>}
    </div>
    </LinkContext.Provider>
  );
}

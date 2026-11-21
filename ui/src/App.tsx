import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { isPhone, isUnchanged, waitForEngine, type ChatSummary, type EngineState, type SearchHit, type WebApi } from "./bridge";
import { Lightbox } from "./cards";
import { Composer } from "./composer";
import { CommandDialog, ConfirmDialog, DownloadDialog, HubDialog, SearchDialog } from "./dialogs";
import { VoiceHubDialog } from "./voicehub";
import { Icon } from "./icons";
import { CallPanel } from "./call";
import { KnowledgeDialog } from "./knowledge";
import { ContextRing } from "./context";
import { LinkContext } from "./markdown";
import { CodeModeActivation } from "./motion";
import { SettingsDialog, FONT_CHOICES, prefetchSettings, type FontChoice } from "./settings";
import { HelpDialog, type SlashCommand } from "./commands";
import { translate } from "./i18n";
import { Sidebar, type ChatActions } from "./sidebar";
import { Transcript } from "./transcript";
import { Decor, IconButton, MenuButton, MotionPresence, fileName, groupModels, shortModel, thinkingName } from "./ui";
import { MODES } from "./projects";
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
  const [dialog, setDialog] = useState<"" | "settings" | "search" | "hub" | "voice-asr" | "voice-tts" | "help" | "knowledge">("");
  const [deleting, setDeleting] = useState<ChatSummary | null>(null);
  const [lightbox, setLightbox] = useState("");
  const [overlayPresent, setOverlayPresent] = useState(false);
  const [focusIndex, setFocusIndex] = useState<{ index: number; nonce: number } | null>(null);
  const [browserOpen, setBrowserOpen] = useState(() => readStored(BROWSER_KEY, ["1", "0"], "0") === "1");

  const appRef = useRef<HTMLDivElement>(null);
  const [workspaceMounted, setWorkspaceMounted] = useState(browserOpen);
  const inCall = Boolean(state?.listening.running);
  const workspaceVisible = browserOpen || inCall;
  const showWorkspace = browserOpen || workspaceMounted;
  useLayoutEffect(() => {
    if (browserOpen) { setWorkspaceMounted(true); return; }
    const slide = appRef.current?.getAnimations().find((animation) =>
      animation instanceof CSSTransition && animation.transitionProperty === "--workspace-progress");
    if (!slide || inCall) { setWorkspaceMounted(false); return; }
    let cancelled = false;
    const unmount = () => { if (!cancelled) setWorkspaceMounted(false); };
    void slide.finished.then(unmount, unmount);
    return () => { cancelled = true; };
  }, [browserOpen, inCall]);

  const [workspaceWidth, setWorkspaceWidth] = useState(() => { try { return Number(localStorage.getItem(WIDTH_KEY)) || 0; } catch { return 0; } });
  const [resizing, setResizing] = useState(false);
  useEffect(() => { writeStored(WIDTH_KEY, String(Math.round(workspaceWidth))); }, [workspaceWidth]);
  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    const handle = event.currentTarget;
    const panel = handle.parentElement;
    if (!panel || !event.isPrimary || event.button !== 0) return;
    event.preventDefault();
    const { clientX, pointerId } = event;
    const initialWidth = panel.getBoundingClientRect().width;
    let dragging = false;

    const move = (moveEvent: PointerEvent) => {
      if (moveEvent.pointerId !== pointerId) return;
      const offset = clientX - moveEvent.clientX;
      if (!dragging) {
        if (Math.abs(offset) < 4 || !handle.isConnected) return;
        dragging = true;
        handle.setPointerCapture(pointerId);
        setResizing(true);
        document.body.classList.add("resizing");
      }
      const max = Math.max(320, window.innerWidth - (sidebarOpen ? 260 : 0) - 380);
      setWorkspaceWidth(Math.min(max, Math.max(320, initialWidth + offset)));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
      window.removeEventListener("blur", stop);
      handle.removeEventListener("lostpointercapture", finish);
      if (dragging) {
        setResizing(false);
        document.body.classList.remove("resizing");
      }
    };
    const finish = (finishEvent: PointerEvent) => { if (finishEvent.pointerId === pointerId) stop(); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
    window.addEventListener("blur", stop);
    handle.addEventListener("lostpointercapture", finish);
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
  const [prefill, setPrefill] = useState<{ chatId: string; text: string; append?: boolean } | null>(null);
  const [theme, setTheme, resolvedTheme] = useTheme();
  const versionRef = useRef(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const draftChatIds = useRef<string[]>([]);
  const updateDraftChatIds = useCallback((ids: string[]) => { draftChatIds.current = ids; }, []);
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
  const newChat = useCallback(() => { if (api) void api.new_chat(draftChatIds.current).then((result) => { done(result.ok ? undefined : result.error); inputRef.current?.focus(); }); }, [api, done]);
  const forkChat = useCallback((chatId: string, index?: number, text?: string) => {
    if (!api) return;
    const request = index === undefined ? api.fork_chat(chatId) : api.fork_chat(chatId, index, text);
    void request.then((result) => {
      done(result.ok ? undefined : result.error);
      if (result.ok) {
        if (window.innerWidth <= 900) setSidebarOpen(false);
        inputRef.current?.focus();
      }
    });
  }, [api, done]);
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
    fork: (chat) => forkChat(chat.id),
    exportChat: (chat, markdown) => { void api.export_chat(chat.id, markdown).then((result) => { if (result.ok) notify(`Сохранено: ${result.path}`, "info"); else if (!result.cancelled) notify(result.error); }); },
    remove: (chat) => setDeleting(chat),
    project: (chat, action) => {
      void api.select_chat(chat.id)
        .then(() => (action === "folder" ? api.code_pick_folder() : api.code_open_folder()))
        .then((result) => done(result.ok || result.cancelled ? undefined : result.error));
    },
    moveToProjects: (chat) => { void api.chat_kind(chat.id, !chat.code).then((result) => done(result.ok ? undefined : result.error)); },
  }, [api, state?.activeChatId, done, notify, forkChat]);

  const stateRef = useRef(state);
  stateRef.current = state;
  const themeRef = useRef(theme);
  themeRef.current = theme;
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
    const tr = (text: string) => translate(text) ?? text;
    const chat = () => {
      const found = stateRef.current?.chats.find((item) => item.id === stateRef.current?.activeChatId);
      if (!found) notify("Этот чат ещё пустой");
      return found;
    };
    const needArg = (arg: string, what: string) => { if (!arg) notify(`Напиши ${what} после команды`); return Boolean(arg); };
    const reply = (result: { ok: boolean; error?: string }) => done(result.ok ? undefined : result.error);
    const thinkingLabel = (value: unknown) => (value === true ? "с размышлением" : value === false ? "без размышления" : thinkingName(value as never).toLowerCase());
    // Each name in "aliases" works as the command too; a name typed in the wrong keyboard layout is understood as well.
    return [
      { name: "new", aliases: ["новый", "чат"], hint: "Новый чат", run: () => newChat() },
      { name: "project", aliases: ["проект"], hint: "Новый проект", run: () => newProject() },
      { name: "model", aliases: ["модель"], args: "название", hint: "Сменить модель",
        options: () => {
          const current = stateRef.current;
          return groupModels(current?.models ?? []).flatMap(([group, names]) =>
            names.map((name) => ({ value: name, label: shortModel(name), hint: group, current: name === current?.settings.model })));
        },
        run: (arg) => {
          const models = stateRef.current?.models ?? [];
          const needle = arg.toLowerCase();
          const found = models.find((name) => name.toLowerCase() === needle) ?? models.find((name) => shortModel(name).toLowerCase().includes(needle) || name.toLowerCase().includes(needle));
          if (!arg) { window.dispatchEvent(new Event("piven:model-menu")); return; }
          if (!found) { notify(`Модель «${arg}» не найдена`); return; }
          if (found !== stateRef.current?.settings.model) void api.set_model(found).then(reply);
        } },
      { name: "think", aliases: ["думай", "размышление"], args: "уровень", hint: "Размышление: выкл, низкий, средний, высокий…",
        options: async () => {
          const options = await api.thinking_options(stateRef.current?.settings.model ?? "");
          return options.values.map((value) => ({ value: tr(thinkingLabel(value)), current: value === options.current }));
        },
        run: (arg) => {
          const model = stateRef.current?.settings.model ?? "";
          void api.thinking_options(model).then((options) => {
            if (!options.values.length) { notify("Эта модель не даёт выбрать размышление"); return; }
            const needle = arg.toLowerCase();
            const off = /^(выкл|нет|без|off|no|none)/.test(needle), on = /^(вкл|да|on|yes)/.test(needle);
            const value = options.values.find((item) => (off && (item === false || item === "none")) || (on && item === true)
              || String(item).toLowerCase() === needle || (needle && (thinkingLabel(item).startsWith(needle) || tr(thinkingLabel(item)).toLowerCase().startsWith(needle))));
            if (value === undefined) { notify(`Можно: ${options.values.map((item) => thinkingLabel(item)).join(", ")}`); return; }
            void api.set_thinking(model, value).then(reply);
          });
        } },
      { name: "mode", aliases: ["режим"], args: "режим", hint: "Режим агента в проекте",
        options: () => MODES.map((mode) => ({ value: tr(mode.short).toLowerCase(), label: tr(mode.name), hint: mode.hint, current: stateRef.current?.code.mode === mode.id })),
        run: (arg) => {
          if (!stateRef.current?.code.on) { notify("Режим выбирается только в проекте"); return; }
          const needle = arg.toLowerCase();
          const found = MODES.find((mode) => mode.id === needle || (needle && [mode.short, mode.name, tr(mode.short), tr(mode.name)].some((text) => text.toLowerCase().startsWith(needle))));
          if (!found) { notify(`Режимы: ${MODES.map((mode) => tr(mode.short).toLowerCase()).join(", ")}`); return; }
          void api.code_set({ mode: found.id }).then(reply);
        } },
      { name: "search", aliases: ["поиск", "найди"], args: "текст", hint: "Найти в чатах и сообщениях", run: (arg) => { setSidebarOpen(true); setSearchPreset({ text: arg, nonce: Date.now() }); window.setTimeout(() => searchRef.current?.focus(), 0); } },
      { name: "web", aliases: ["интернет", "гугл"], args: "запрос", hint: "Найти в интернете во встроенном браузере", run: (arg) => {
        if (!arg) { setBrowserOpen(true); return; }
        openLink(`https://search.brave.com/search?q=${encodeURIComponent(arg)}`);
      } },
      { name: "image", aliases: ["картинка", "нарисуй"], args: "описание", hint: "Нарисовать картинку", run: (arg) => { if (needArg(arg, "что нарисовать")) void api.send_message(`${language === "en" ? "Draw" : "Нарисуй"} ${arg}`, []).then(reply); } },
      { name: "remember", aliases: ["запомни"], args: "факт", hint: "Запомнить факт о тебе", run: (arg) => {
        if (needArg(arg, "что запомнить")) void api.memory_add_fact(arg).then((result) => notify(result.ok ? "Запомнил" : "Это уже есть в памяти", "info"));
      } },
      { name: "retry", aliases: ["заново", "повтори"], hint: "Ответить на последнее сообщение заново", run: () => { void api.retry_last().then(reply); } },
      { name: "copy", aliases: ["скопируй", "копировать"], hint: "Скопировать последний ответ", run: () => { const text = lastAnswer(); if (text) copy(text); else notify("Ответов пока нет"); } },
      { name: "speak", aliases: ["озвучь", "прочитай"], hint: "Прочитать последний ответ вслух", run: () => { const text = lastAnswer(); if (text) void api.speak(text).then(reply); else notify("Ответов пока нет"); } },
      { name: "rename", aliases: ["переименуй", "имя"], args: "название", hint: "Переименовать чат", run: (arg) => { const current = chat(); if (current && needArg(arg, "новое название")) actions.rename(current, arg); } },
      { name: "pin", aliases: ["закрепи"], hint: "Закрепить или открепить чат", run: () => { const current = chat(); if (current) actions.pin(current); } },
      { name: "export", aliases: ["сохрани", "экспорт"], hint: "Сохранить чат в файл Markdown", run: () => { const current = chat(); if (current) actions.exportChat(current, true); } },
      { name: "delete", aliases: ["удали"], hint: "Удалить чат", run: () => { const current = chat(); if (current) actions.remove(current); } },
      { name: "theme", aliases: ["тема"], args: "название", hint: "Сменить тему оформления",
        options: () => THEMES.map(([id, label]) => ({ value: tr(label), current: id === themeRef.current })),
        run: (arg) => {
          const needle = arg.toLowerCase();
          const found = THEMES.find(([id, label]) => id === needle || label.toLowerCase().startsWith(needle) || tr(label).toLowerCase().startsWith(needle));
          if (!arg || !found) { notify(`Темы: ${THEMES.map(([, label]) => label).join(", ")}`); return; }
          setTheme(found[0]);
        } },
      { name: "lang", aliases: ["язык", "language"], args: "язык", hint: "Сменить язык интерфейса",
        options: () => LANGUAGES.map(([id, label]) => ({ value: id, label, current: id === language })),
        run: (arg) => {
          const needle = arg.toLowerCase();
          const found = LANGUAGES.find(([id, label]) => id === needle || (needle && label.toLowerCase().startsWith(needle)) || (id === "en" && /^(англ|eng)/.test(needle)));
          if (!found) { notify(`Языки: ${LANGUAGES.map(([id, label]) => `${label} (${id})`).join(", ")}`); return; }
          setLanguageChoice(found[0]);
        } },
      { name: "browser", aliases: ["браузер"], hint: "Показать или скрыть браузер", run: () => setBrowserOpen((open) => !open) },
      { name: "settings", aliases: ["настройки"], hint: "Открыть настройки", run: () => setDialog("settings") },
      { name: "stop", aliases: ["стоп"], hint: "Остановить ответ", run: () => { if (stateRef.current?.busy) stop(); else notify("Сейчас ничего не выполняется", "info"); } },
      { name: "help", aliases: ["помощь", "команды"], hint: "Все команды и сочетания клавиш", run: () => setDialog("help") },
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
  const active = state.chats.find((chat) => chat.id === state.activeChatId);
  const parent = active?.branchOf ? state.chats.find((chat) => chat.id === active.branchOf) : undefined;
  const children = state.chats.filter((chat) => chat.branchOf === state.activeChatId);
  const projectRoot = state.code.on ? state.code.root : "";
  const showWorkspaceToggle = !isPhone && !state.listening.running;
  const workspaceToggleLabel = browserOpen ? "Скрыть панель (Ctrl+D)" : "Браузер и файлы (Ctrl+D)";
  const overlayOpen = Boolean(dialog || deleting || lightbox || state.confirm);

  return (
    <LinkContext.Provider value={openLink}>
    <div ref={appRef} className={`app ${sidebarOpen ? "" : "sidebar-hidden"} ${workspaceVisible ? "workspace-open" : ""} ${showWorkspace ? "workspace-sliding" : ""}`}>
      <Sidebar api={api} state={state} actions={actions} searchRef={searchRef} onNewChat={newChat} open={sidebarOpen}
        onToggle={() => setSidebarOpen((open) => !open)}
        onOpenHit={openHit} searchPreset={searchPreset} onSettings={() => setDialog("settings")} />
      {sidebarOpen && <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />}

      <main className="main">
        {projectRoot && <div className="main-corner main-corner-left">
          <span className="project-header-folder" title={projectRoot}>
            <Icon name="folder" size={15} />
            <span data-i18n-skip>{fileName(projectRoot.replace(/[\\/]+$/, ""))}</span>
          </span>
        </div>}
        <div className={`chat-tools ${showWorkspaceToggle ? "with-workspace-toggle" : ""}`}>
          {(parent || children.length > 0) && <MenuButton icon="branch" label="Ветки чата" items={[
            ...(parent ? [{ icon: "chat" as const, label: "Исходный чат", hint: parent.title, onClick: () => actions.select(parent) }] : []),
            ...children.map((chat) => ({ icon: "branch" as const, label: chat.title, onClick: () => actions.select(chat) })),
          ]} />}
          {!isPhone && <IconButton icon="database" label="База знаний" active={dialog === "knowledge"} onClick={() => setDialog("knowledge")} />}
          <button type="button" className={`code-toggle ${state.code.on ? "on" : ""}`} aria-pressed={state.code.on}
            title={state.code.on ? "Режим кода включён: слева проекты, агент сам пишет файлы и запускает команды. Нажми, чтобы вернуться к чатам" : "Включить режим кода: слева будут проекты, агент сам пишет файлы и запускает команды"}
            onClick={() => { void api.code_mode(!state.code.on).then((result) => done(result.ok ? undefined : result.error)); }}>
            <Icon name="code" size={15} /><span>Код</span>
            <CodeModeActivation enabled={state.code.on} />
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
              onFork={(index) => forkChat(state.activeChatId, index, state.items[index].text)}
              onPrefill={(text) => setPrefill({ chatId: state.activeChatId, text })} onNotice={done} />

        <div className="composer-dock" ref={trackDockHeight}>
          <Composer api={api} state={state} inputRef={inputRef} prefill={prefill} commands={commands} onDraftChats={updateDraftChatIds} onStop={stop} onError={done} onOpenHub={() => setDialog("hub")} onOpenVoiceHub={(kind = "tts") => setDialog(`voice-${kind}`)}
            onSent={(queued) => { if (queued) notify("Отправится после текущего ответа", "info"); void poll(); }} />
        </div>
      </main>

      {showWorkspaceToggle && (
        <button type="button" className="icon-btn workspace-toggle" aria-expanded={browserOpen}
          aria-controls="workspace-panel" aria-label={workspaceToggleLabel}
          title={workspaceToggleLabel} onClick={() => setBrowserOpen((open) => !open)}>
          <Icon name={browserOpen ? "workspace" : "workspaceOff"} size={18} />
        </button>
      )}

      {!isPhone && (
        <aside id="workspace-panel" className={`workspace ${inCall ? "in-call" : ""}`} aria-label={inCall ? "Звонок" : "Рабочая панель"} inert={!workspaceVisible}
          style={workspaceWidth ? { ["--ws-w" as string]: `${workspaceWidth}px` } : undefined}>
          <div className={`workspace-resize ${resizing ? "dragging" : ""}`} role="separator" aria-orientation="vertical" title="Потяни, чтобы изменить ширину; двойной щелчок — по умолчанию"
            onPointerDown={startResize} onDoubleClick={() => setWorkspaceWidth(0)} />
          {inCall && <CallPanel api={api} state={state} onError={done} />}

          {showWorkspace && <div className={inCall ? "workspace-hidden" : "workspace-slot"}>
            <Workspace api={api} state={state} tab={workspaceTab} setTab={setWorkspaceTab} browserRequest={browserRequest}
              onReference={(path) => setPrefill({ chatId: state.activeChatId, text: `\`${path}\` `, append: true })}
              covered={overlayOpen || overlayPresent || inCall} />
          </div>}
        </aside>
      )}

      <MotionPresence onPresentChange={setOverlayPresent}>
        {overlayOpen && <>
          {dialog === "settings" && <SettingsDialog state={state} api={api} theme={theme} setTheme={setTheme} fontChoice={fontChoice} setFontChoice={setFontChoice} language={language} setLanguage={setLanguageChoice} onClose={() => setDialog("")}
            onOpenHub={() => setDialog("hub")} onOpenVoiceHub={(kind) => setDialog(`voice-${kind}`)} />}
          {dialog === "search" && <SearchDialog api={api} onClose={() => setDialog("")} onOpen={openHit} />}
          {dialog === "help" && <HelpDialog commands={commands} onClose={() => setDialog("")} />}
          {dialog === "knowledge" && <KnowledgeDialog key={state.activeChatId} api={api} chatId={state.activeChatId} onClose={() => setDialog("")} />}
          {(dialog === "voice-asr" || dialog === "voice-tts") && <VoiceHubDialog api={api} initialKind={dialog === "voice-asr" ? "asr" : "tts"}
            onClose={() => setDialog("settings")} onDone={() => notify("Голосовая модель скачана", "info")} />}
          {dialog === "hub" && <HubDialog api={api} onClose={() => setDialog("")} onDone={() => { void poll(); notify("Модель скачана", "info"); }} />}
          {deleting && <ConfirmDialog title="Удалить чат?" text={`«${deleting.title}» и вся его история будут удалены. Это нельзя отменить.`} confirmLabel="Удалить" danger
            onClose={() => setDeleting(null)} onConfirm={() => { void api.delete_chat(deleting.id).then((result) => done(result.ok ? undefined : result.error)); }} />}
          {state.confirm?.kind === "download" && <DownloadDialog confirm={state.confirm} api={api} />}
          {state.confirm?.kind === "command" && <CommandDialog confirm={state.confirm} api={api} />}
          {lightbox && <Lightbox api={api} path={lightbox} onClose={() => setLightbox("")} />}
        </>}
      </MotionPresence>
      {toast && <div className={`toast ${toast.kind}`} role="status"><Icon name={toast.kind === "error" ? "alert" : "check"} size={16} />{toast.text}</div>}
    </div>
    </LinkContext.Provider>
  );
}

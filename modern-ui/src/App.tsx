import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { isUnchanged, waitForEngine, type ChatSummary, type DialogueItem, type EngineState, type SettingsDetails, type ThinkingValue, type WebApi } from "./bridge";
import { Icon, type IconName } from "./icons";
import { Markdown } from "./markdown";
import { Board, type BoardCard } from "./board";
import logoUrl from "./assets/piven_logo.png";

type ThemeChoice = "system" | "light" | "dark";
const THEME_KEY = "piven-ui-theme";
const IMAGE_PATTERN = /\.(png|jpe?g|webp|bmp|gif|tiff?)$/i;
const fileName = (path: string) => path.split(/[\\/]/).pop() || path;


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

function IconButton({ icon, label, onClick, className = "", disabled = false, size = 18 }: { icon: IconName; label: string; onClick?: () => void; className?: string; disabled?: boolean; size?: number }) {
  return (
    <button className={`icon-btn ${className}`} type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled}>
      <Icon name={icon} size={size} />
    </button>
  );
}

function useOutsideClose(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => { if (ref.current && !ref.current.contains(event.target as Node)) close(); };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open, close]);
  return ref;
}

/* ---------------- sidebar ---------------- */

function ChatRow({ chat, active, disabled, api, onSelect, onDone }: { chat: ChatSummary; active: boolean; disabled: boolean; api: WebApi; onSelect: () => void; onDone: (error?: string) => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(chat.title);
  const close = useCallback(() => setMenuOpen(false), []);
  const menuRef = useOutsideClose(menuOpen, close);
  const commit = () => {
    setRenaming(false);
    const clean = title.trim();
    if (clean && clean !== chat.title) void api.rename_chat(chat.id, clean).then((result) => onDone(result.ok ? undefined : result.error));
    else setTitle(chat.title);
  };
  if (renaming) {
    return (
      <div className="chat-row renaming">
        <input autoFocus value={title} maxLength={80} onChange={(event) => setTitle(event.target.value)} onBlur={commit}
          onKeyDown={(event) => { if (event.key === "Enter") commit(); if (event.key === "Escape") { setTitle(chat.title); setRenaming(false); } }} />
      </div>
    );
  }
  return (
    <div className={`chat-row ${active ? "active" : ""} ${menuOpen ? "menu-open" : ""}`} ref={menuRef}>
      <button type="button" className="chat-row-main" disabled={disabled} onClick={onSelect} onDoubleClick={() => setRenaming(true)} title={chat.title}>
        {chat.pinned && <Icon name="pin" size={13} className="chat-row-pin" />}
        <span className="chat-row-title">{chat.title}</span>
      </button>
      <button type="button" className="chat-row-more" aria-label="Действия с чатом" onClick={() => setMenuOpen((open) => !open)}><Icon name="more" size={16} /></button>
      {menuOpen && (
        <div className="popover chat-menu" role="menu">
          <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); setTitle(chat.title); setRenaming(true); }}><Icon name="edit" size={15} /> Переименовать</button>
          <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); void api.pin_chat(chat.id, !chat.pinned).then(() => onDone()); }}><Icon name="pin" size={15} /> {chat.pinned ? "Открепить" : "Закрепить"}</button>
        </div>
      )}
    </div>
  );
}

/* ---------------- model picker ---------------- */

function ModelPicker({ state, api, onDone }: { state: EngineState; api: WebApi; onDone: (error?: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const close = useCallback(() => { setOpen(false); setQuery(""); }, []);
  const ref = useOutsideClose(open, close);
  const model = state.settings.model;
  const models = state.models.filter((name) => name.toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <div className="model-picker" ref={ref}>
      <button type="button" className="model-trigger" disabled={state.busy || !state.models.length} onClick={() => setOpen((value) => !value)} title="Модель Ollama">
        <span className={`dot ${state.models.length ? "ok" : "warn"}`} />
        <span className="model-name">{model || (state.modelsError ? "Ollama недоступна" : "Выбери модель")}</span>
        <Icon name="chevronDown" size={15} />
      </button>
      {open && (
        <div className="popover model-menu">
          {state.models.length > 6 && <div className="popover-search"><Icon name="search" size={15} /><input autoFocus placeholder="Найти модель" value={query} onChange={(event) => setQuery(event.target.value)} /></div>}
          <div className="popover-list">
            {models.map((name) => (
              <button key={name} type="button" className={name === model ? "selected" : ""} onClick={() => { close(); if (name !== model) void api.set_model(name).then((result) => onDone(result.ok ? undefined : result.error)); }}>
                <span>{name}</span>{name === model && <Icon name="check" size={15} />}
              </button>
            ))}
            {!models.length && <div className="popover-empty">Ничего не найдено</div>}
          </div>
          <button type="button" className="popover-footer" onClick={() => { close(); void api.refresh_models().then(() => onDone()); }}><Icon name="refresh" size={14} /> Обновить список</button>
        </div>
      )}
    </div>
  );
}

/* ---------------- messages ---------------- */

function Attachment({ api, path }: { api: WebApi; path: string }) {
  const [src, setSrc] = useState("");
  const isImage = IMAGE_PATTERN.test(path);
  useEffect(() => {
    let alive = true;
    if (isImage) void api.image_data(path).then((data) => { if (alive) setSrc(data); });
    return () => { alive = false; };
  }, [api, path, isImage]);
  const open = () => { void api.open_file(path); };
  if (isImage) {
    return <button type="button" className={`attachment-image ${src ? "" : "loading"}`} title="Открыть в просмотрщике" onClick={open}>{src && <img src={src} alt={fileName(path)} />}</button>;
  }
  return (
    <button type="button" className="attachment-file" onClick={open}>
      <span className="attachment-icon"><Icon name={/\.pptx$/i.test(path) ? "presentation" : "file"} size={18} /></span>
      <span className="attachment-copy"><strong>{fileName(path)}</strong><small>Открыть файл</small></span>
    </button>
  );
}

function Logo({ size = 22, pulse = false }: { size?: number; pulse?: boolean }) {
  return <img className={`logo ${pulse ? "pulse" : ""}`} src={logoUrl} width={size} height={size} alt="" draggable={false} />;
}

function CardHeader({ lead, title, meta, index, children }: { lead: ReactNode; title: string; meta?: string; index?: number; children?: ReactNode }) {
  return (
    <div className="card-head" data-drag-handle title="Потяни, чтобы переместить карточку">
      <span className="card-lead">{lead}</span>
      <strong>{title}</strong>
      {meta && <span className="card-meta">{meta}</span>}
      <span className="card-head-spacer" />
      {children}
    </div>
  );
}

const ROLE_WIDTH: Record<string, number> = { assistant: 640, user: 460, computer: 460, system: 520, thinking: 640 };

function MessageCard({ api, item, model, index, onCopy }: { api: WebApi; item: DialogueItem; model: string; index: number; onCopy: (text: string) => void }) {
  const attachments = item.images.length > 0 && <div className="attachments">{item.images.map((path) => <Attachment key={path} api={api} path={path} />)}</div>;
  if (item.role === "system") {
    return (
      <div className="card card-system"><div className="card-inner">
        <CardHeader index={index} lead={<Icon name="monitor" size={13} />} title="Система" />
        <div className="card-body"><p className="plain">{item.text}</p>{attachments}</div>
      </div></div>
    );
  }
  if (item.role === "user" || item.role === "computer") {
    return (
      <div className="card card-user"><div className="card-inner">
        <CardHeader index={index} lead={<Icon name={item.role === "computer" ? "volume" : "user"} size={13} />} title={item.role === "computer" ? "Звук компьютера" : "Вы"}>
          <IconButton icon="copy" label="Копировать" size={14} className="card-action" onClick={() => onCopy(item.text)} />
        </CardHeader>
        <div className="card-body">{attachments}{item.text && <p className="plain">{item.text}</p>}</div>
      </div></div>
    );
  }
  return (
    <div className="card card-assistant"><div className="card-inner">
      <CardHeader index={index} lead={<Logo size={20} />} title="PIVEN" meta={model}>
        <IconButton icon="copy" label="Копировать ответ" size={14} className="card-action" onClick={() => onCopy(item.text)} />
      </CardHeader>
      <div className="card-body scrollable">{item.text && <Markdown text={item.text} onCopy={onCopy} />}{attachments}</div>
    </div></div>
  );
}

function ThinkingCard({ state, onStop }: { state: EngineState; onStop: () => void }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="card card-assistant card-thinking"><div className="card-inner">
      <CardHeader lead={<Logo size={20} pulse />} title="PIVEN" meta={state.settings.model}>
        <button type="button" className="stop-chip" onClick={onStop}>Стоп</button>
      </CardHeader>
      <div className="card-body">
        <div className="thinking-line">
          <span className="activity">{state.activity || "Думаю"}</span>
          {state.reasoning && <button type="button" className="link-btn" onClick={() => setExpanded((value) => !value)}>{expanded ? "Скрыть рассуждения" : "Рассуждения"}<Icon name="chevronDown" size={13} className={expanded ? "flip" : ""} /></button>}
        </div>
        {expanded && state.reasoning && <pre className="reasoning scrollable">{state.reasoning.slice(-4000)}</pre>}
      </div>
    </div></div>
  );
}

/* ---------------- settings ---------------- */

type SectionId = "look" | "model" | "voice" | "images" | "code" | "integrations" | "data";
const SECTIONS: { id: SectionId; title: string }[] = [
  { id: "look", title: "Оформление" },
  { id: "model", title: "Модель" },
  { id: "voice", title: "Голос и микрофон" },
  { id: "images", title: "Картинки" },
  { id: "code", title: "Работа с кодом" },
  { id: "integrations", title: "Интеграции" },
  { id: "data", title: "Данные" },
];

const THINKING_NAMES: Record<string, string> = { low: "Низкий", medium: "Средний", high: "Высокий", true: "Включено", false: "Выключено" };
const thinkingName = (value: ThinkingValue | null) => (value === null ? "" : THINKING_NAMES[String(value)] ?? String(value));

function Field({ label, hint, error, children }: { label: string; hint?: ReactNode; error?: string; children: ReactNode }) {
  return (
    <div className={`field ${error ? "has-error" : ""}`}>
      <div className="field-label"><strong>{label}</strong>{hint && <small>{hint}</small>}</div>
      <div className="field-control">{children}</div>
      {error && <div className="field-error">{error}</div>}
    </div>
  );
}

function Switch({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} className={`switch ${checked ? "on" : ""}`} onClick={() => onChange(!checked)}><span /></button>;
}

/** Text input that saves on Enter or when focus leaves, and keeps the typed value if it was rejected. */
function TextSetting({ value, placeholder, onCommit, mono = false }: { value: string; placeholder?: string; onCommit: (value: string) => void; mono?: boolean }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => { if (draft !== value) onCommit(draft); };
  return <input className={`text-input ${mono ? "mono" : ""}`} value={draft} placeholder={placeholder} spellCheck={false}
    onChange={(event) => setDraft(event.target.value)} onBlur={commit} onKeyDown={(event) => { if (event.key === "Enter") commit(); }} />;
}

function SettingsDialog({ state, api, theme, setTheme, onClose }: { state: EngineState; api: WebApi; theme: ThemeChoice; setTheme: (value: ThemeChoice) => void; onClose: () => void }) {
  const ref = useOutsideClose(true, onClose);
  const [section, setSection] = useState<SectionId>("look");
  const [details, setDetails] = useState<SettingsDetails | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [savedAt, setSavedAt] = useState(0);
  const [prompt, setPrompt] = useState("");
  const [thinking, setThinking] = useState<{ values: ThinkingValue[]; default: ThinkingValue | null; current: ThinkingValue; error: string } | null>(null);
  const model = state.settings.model;

  const reload = useCallback(() => api.settings_details().then((next) => { setDetails(next); setPrompt(next.systemPrompt); }), [api]);
  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => { if (model) void api.thinking_options(model).then(setThinking); }, [api, model]);

  const save = (patch: Record<string, unknown>) => api.update_settings(patch).then((result) => {
    setErrors((current) => {
      const next = { ...current };
      Object.keys(patch).forEach((key) => { delete next[key]; });
      return { ...next, ...result.errors };
    });
    if (result.saved.length) { setSavedAt(Date.now()); void reload(); }
    return result;
  });

  const [showSaved, setShowSaved] = useState(false);
  useEffect(() => {
    if (!savedAt) return;
    setShowSaved(true);
    const timer = window.setTimeout(() => setShowSaved(false), 1800);
    return () => window.clearTimeout(timer);
  }, [savedAt]);

  const d = details;
  const promptDirty = d !== null && prompt.trim() !== d.systemPrompt.trim();
  return (
    <div className="modal-backdrop">
      <div className="modal settings" role="dialog" aria-modal="true" aria-label="Настройки" ref={ref}>
        <nav className="settings-nav">
          <h3>Настройки</h3>
          {SECTIONS.map((item) => <button key={item.id} type="button" className={section === item.id ? "on" : ""} onClick={() => setSection(item.id)}>{item.title}</button>)}
          <span className="settings-nav-spacer" />
          <span className={`saved-note ${showSaved ? "visible" : ""}`}>Сохранено</span>
        </nav>
        <div className="settings-pane">
          <header className="settings-pane-head"><h4>{SECTIONS.find((item) => item.id === section)?.title}</h4><IconButton icon="close" label="Закрыть (Esc)" onClick={onClose} /></header>
          {!d ? <p className="pane-note">Загружаю…</p> : <div className="settings-fields">
            {section === "look" && <>
              <Field label="Тема окна" hint="Только для этого окна, обычное окно Компаньона не меняется.">
                <div className="segmented">
                  {([["system", "Как в Windows"], ["light", "Светлая"], ["dark", "Тёмная"]] as const).map(([value, label]) => (
                    <button key={value} type="button" className={theme === value ? "on" : ""} onClick={() => setTheme(value)}>{label}</button>
                  ))}
                </div>
              </Field>
            </>}

            {section === "model" && <>
              <Field label="Модель Ollama" hint={state.status || "Список берётся из Ollama."}>
                <select className="select" value={model} disabled={!state.models.length}
                  onChange={(event) => { void api.set_model(event.target.value).then(() => { setSavedAt(Date.now()); }); }}>
                  {state.models.map((name) => <option key={name} value={name}>{name}</option>)}
                </select>
              </Field>
              <Field label="Размышление" hint={thinking?.error ? `Не удалось узнать у модели: ${thinking.error}` : thinking && !thinking.values.length ? "Эта модель не умеет переключать размышление." : `По умолчанию у модели: ${thinkingName(thinking?.default ?? null) || "не указано"}.`}>
                <select className="select" value={String(thinking?.current ?? "__auto__")} disabled={!thinking || !thinking.values.length}
                  onChange={(event) => {
                    const raw = event.target.value;
                    const value: ThinkingValue = raw === "true" ? true : raw === "false" ? false : raw;
                    void api.set_thinking(model, value).then(() => { setSavedAt(Date.now()); void api.thinking_options(model).then(setThinking); });
                  }}>
                  <option value="__auto__">Как решит модель</option>
                  {thinking?.values.map((value) => <option key={String(value)} value={String(value)}>{thinkingName(value)}</option>)}
                </select>
              </Field>
              <Field label="Системный промпт" hint="Как компаньон должен себя вести. Применяется к следующим сообщениям." error={errors.systemPrompt}>
                <textarea className="prompt-input" value={prompt} onChange={(event) => setPrompt(event.target.value)} spellCheck={false} />
                <div className="prompt-actions">
                  <span>{prompt.length} симв.</span>
                  <button type="button" className="text-btn" disabled={prompt.trim() === d.defaultSystemPrompt.trim()} onClick={() => setPrompt(d.defaultSystemPrompt)}>Вернуть стандартный</button>
                  <button type="button" className="text-btn" disabled={!promptDirty} onClick={() => setPrompt(d.systemPrompt)}>Отменить</button>
                  <button type="button" className="primary-btn" disabled={!promptDirty} onClick={() => { void save({ systemPrompt: prompt }); }}>Сохранить промпт</button>
                </div>
              </Field>
            </>}

            {section === "voice" && <>
              <Field label="Озвучивать ответы" hint="Компаньон читает ответы вслух через локальный Qwen3-TTS.">
                <Switch label="Озвучивать ответы" checked={d.speechEnabled} onChange={(value) => { void save({ speechEnabled: value }); }} />
              </Field>
              <Field label="Голос">
                <select className="select" value={d.voice} onChange={(event) => { void save({ voice: event.target.value }); }}>
                  {d.voices.map((voice) => <option key={voice} value={voice}>{voice === "Russian" ? "Русский" : voice}</option>)}
                </select>
              </Field>
              <Field label="Микрофон" hint={d.micError || "Используется, когда в обычном окне включено прослушивание."}>
                <select className="select" value={d.micDevice} onChange={(event) => { void save({ micDevice: event.target.value }); }}>
                  <option value="">Как в Windows</option>
                  {d.microphones.map((name) => <option key={name} value={name}>{name}</option>)}
                  {d.micDevice && !d.microphones.includes(d.micDevice) && <option value={d.micDevice}>{d.micDevice} (не подключён)</option>}
                </select>
              </Field>
              <Field label="Чувствительность микрофона" hint="Чем выше, тем тише голос он услышит, но и шум тоже.">
                <div className="range-row">
                  <input type="range" min={1} max={100} defaultValue={d.micSensitivity} key={`mic-${d.micSensitivity}`}
                    onMouseUp={(event) => { void save({ micSensitivity: Number((event.target as HTMLInputElement).value) }); }}
                    onKeyUp={(event) => { void save({ micSensitivity: Number((event.target as HTMLInputElement).value) }); }}
                    onInput={(event) => { const label = (event.target as HTMLInputElement).nextElementSibling; if (label) label.textContent = (event.target as HTMLInputElement).value; }} />
                  <span className="range-value">{d.micSensitivity}</span>
                </div>
              </Field>
              <Field label="Смотреть на экран раз в" hint="Интервал снимков экрана для комментариев, от 10 до 600 секунд.">
                <div className="number-row">
                  <TextSetting value={String(d.screenInterval)} onCommit={(value) => { void save({ screenInterval: Number(value) }); }} />
                  <span>сек.</span>
                </div>
              </Field>
            </>}

            {section === "images" && <>
              <Field label="Адрес ComfyUI" error={errors.comfyUrl} hint="Если ComfyUI запущен на этом компьютере, обычно это http://127.0.0.1:8188.">
                <TextSetting mono value={d.comfyUrl} placeholder="http://127.0.0.1:8188" onCommit={(value) => { void save({ comfyUrl: value }); }} />
              </Field>
              <Field label="Workflow" error={errors.comfyWorkflow} hint="JSON-файл ComfyUI, через который рисуются картинки. Пустое поле вернёт стандартный.">
                <div className="path-row">
                  <TextSetting mono value={d.comfyWorkflow} onCommit={(value) => { void save({ comfyWorkflow: value }); }} />
                  <button type="button" className="text-btn bordered" onClick={() => { void api.pick_path("workflow").then((path) => { if (path) void save({ comfyWorkflow: path }); }); }}>Выбрать…</button>
                </div>
              </Field>
            </>}

            {section === "code" && <>
              <Field label="Папка проекта" error={errors.projectRoot} hint="Здесь компаньон читает и правит файлы, когда просишь что-то сделать с кодом.">
                <div className="path-row">
                  <TextSetting mono value={d.projectRoot} onCommit={(value) => { void save({ projectRoot: value }); }} />
                  <button type="button" className="text-btn bordered" onClick={() => { void api.pick_path("folder").then((path) => { if (path) void save({ projectRoot: path }); }); }}>Выбрать…</button>
                </div>
              </Field>
            </>}

            {section === "integrations" && <>
              {([["ollama", "Ollama", "Ответы, код и презентации. Если выключить, текущий ответ остановится."],
                 ["comfyui", "ComfyUI", "Рисование картинок."],
                 ["twitch", "Twitch", "Отправка сообщений в чат канала из обычного окна."]] as const).map(([key, label, hint]) => (
                <Field key={key} label={label} hint={hint}>
                  <Switch label={label} checked={d.integrations[key] !== false} onChange={(value) => { void save({ integrations: { [key]: value } }); }} />
                </Field>
              ))}
              <Field label="Twitch-канал" error={errors.twitchChannel} hint="Без решётки, например twitchdev.">
                <TextSetting mono value={d.twitchChannel} placeholder="канал" onCommit={(value) => { void save({ twitchChannel: value }); }} />
              </Field>
            </>}

            {section === "data" && <>
              <Field label="Папка с данными" hint={<span className="mono">{d.dataDir}</span>}>
                <div className="button-row">
                  <button type="button" className="text-btn bordered" onClick={() => { void api.open_data_folder("folder"); }}>Открыть папку</button>
                  <button type="button" className="text-btn bordered" onClick={() => { void api.open_data_folder("log"); }}>Открыть журнал</button>
                </div>
              </Field>
              <p className="pane-note">Тут лежат настройки, все чаты, журналы и нарисованные картинки. Эти настройки общие с обычным окном Компаньона.</p>
            </>}
          </div>}
        </div>
      </div>
    </div>
  );
}

/* ---------------- composer ---------------- */

function Composer({ api, state, draft, setDraft, onSend, onStop, inputRef }: { api: WebApi; state: EngineState; draft: string; setDraft: (value: string) => void; onSend: () => void; onStop: () => void; inputRef: RefObject<HTMLTextAreaElement | null> }) {
  const [hint, setHint] = useState("");
  useEffect(() => {
    const text = draft.trim();
    if (!text) { setHint(""); return; }
    const timer = window.setTimeout(() => { void api.route_hint(text).then((result) => setHint(result.label)); }, 160);
    return () => window.clearTimeout(timer);
  }, [api, draft]);
  useEffect(() => {
    const element = inputRef.current;
    if (!element) return;
    element.style.height = "0px";
    element.style.height = `${Math.min(220, element.scrollHeight)}px`;
  }, [draft, inputRef]);
  const submit = (event: FormEvent) => { event.preventDefault(); onSend(); };
  const canSend = Boolean(draft.trim());
  return (
    <form className="composer" onSubmit={submit}>
      {hint && <div className="route-chip">{hint}</div>}
      {/* Clicking anywhere in the box (not just on the text line) puts the cursor in the field. */}
      <div className="composer-box" onMouseDown={(event) => { if (!(event.target as HTMLElement).closest("button, textarea")) { event.preventDefault(); inputRef.current?.focus(); } }}>
        <textarea ref={inputRef} rows={1} aria-label="Сообщение" placeholder={state.busy ? "Можно писать дальше, отправлю после текущего ответа" : "Сообщение"}
          value={draft} onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend(); } }} />
        {state.busy && !canSend
          ? <button type="button" className="send-btn stop" onClick={onStop} title="Esc">Стоп</button>
          : <button type="submit" className="send-btn" disabled={!canSend} title="Enter, перенос строки Shift+Enter">Отправить</button>}
      </div>
    </form>
  );
}

/* ---------------- app ---------------- */

export default function App() {
  const [api, setApi] = useState<WebApi | null>(null);
  const [engineMissing, setEngineMissing] = useState(false);
  const [state, setState] = useState<EngineState | null>(null);
  const [draft, setDraft] = useState("");
  const [toast, setToast] = useState("");
  const [query, setQuery] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 860);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [theme, setTheme, resolvedTheme] = useTheme();
  // Keep the native Windows title bar in the page's colours.
  useEffect(() => { if (api) void api.set_title_theme(resolvedTheme === "dark"); }, [api, resolvedTheme]);
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

  const poll = useCallback(async () => {
    if (!api) return;
    const result = await api.poll(versionRef.current);
    if (isUnchanged(result)) return;
    versionRef.current = result.version;
    setState(result);
  }, [api]);

  useEffect(() => {
    if (!api) return;
    const timer = window.setInterval(() => { void poll(); }, state?.busy ? 300 : 1000);
    return () => window.clearInterval(timer);
  }, [api, poll, state?.busy]);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(""), 3600);
    return () => window.clearTimeout(timeout);
  }, [toast]);
  useEffect(() => { if (state?.notice) setToast(state.notice); }, [state?.notice]);

  const done = useCallback((error?: string) => { if (error) setToast(error); void poll(); }, [poll]);
  const copy = useCallback((text: string) => { if (api) void api.copy_text(text).then(() => setToast("Скопировано")); }, [api]);
  const newChat = useCallback(() => { if (api) void api.new_chat().then((result) => { done(result.ok ? undefined : result.error); inputRef.current?.focus(); }); }, [api, done]);
  const stop = useCallback(() => { if (api) void api.interrupt().then(() => done()); }, [api, done]);

  const send = useCallback(() => {
    const text = draft.trim();
    if (!text || !api) return;
    void api.send(text).then((result) => {
      if (result.ok) { setDraft(""); if (result.queued) setToast("Отправлю после текущего ответа"); }
      done(result.ok ? undefined : result.error);
    });
  }, [api, draft, done]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.ctrlKey || event.metaKey;
      if (mod && event.key.toLowerCase() === "k") { event.preventDefault(); setSidebarOpen(true); window.setTimeout(() => searchRef.current?.focus(), 0); }
      else if (mod && event.key.toLowerCase() === "n") { event.preventDefault(); newChat(); }
      else if (mod && event.key === ",") { event.preventDefault(); setSettingsOpen(true); }
      else if (mod && event.key.toLowerCase() === "b") { event.preventDefault(); setSidebarOpen((open) => !open); }
      else if (event.key === "Escape" && state?.busy && !settingsOpen) stop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [newChat, stop, state?.busy, settingsOpen]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const chats = state?.chats ?? [];
    return needle ? chats.filter((chat) => chat.title.toLowerCase().includes(needle)) : chats;
  }, [state?.chats, query]);

  if (engineMissing) {
    return <div className="splash"><Logo size={64} /><h2>Нет связи с движком</h2><p>Этот интерфейс открывается ярлыком «Запустить веб-интерфейс» в папке Компаньона.</p></div>;
  }
  if (!api || !state) {
    return <div className="splash"><Logo size={64} pulse /><p>Загружаю чаты…</p></div>;
  }

  const pinned = filtered.filter((chat) => chat.pinned);
  const others = filtered.filter((chat) => !chat.pinned);
  const renderRows = (chats: ChatSummary[]) => chats.map((chat) => (
    <ChatRow key={`${chat.id}-${chat.title}`} chat={chat} api={api} active={chat.id === state.activeChatId} disabled={state.busy && chat.id !== state.activeChatId}
      onSelect={() => { if (chat.id !== state.activeChatId) void api.select_chat(chat.id).then((result) => done(result.ok ? undefined : result.error)); }} onDone={done} />
  ));
  const empty = !state.items.length && !state.busy;
  const recent = state.chats.filter((chat) => chat.id !== state.activeChatId && chat.count > 1).slice(0, 4);
  const model = state.settings.model;
  const cards: BoardCard[] = state.items.map((item, index) => ({
    key: String(index), role: item.role, width: ROLE_WIDTH[item.role] ?? 520,
    node: <MessageCard api={api} item={item} model={model} index={index} onCopy={copy} />,
  }));
  if (state.busy) cards.push({ key: "thinking", role: "thinking", width: ROLE_WIDTH.thinking, node: <ThinkingCard state={state} onStop={stop} /> });

  return (
    <div className={`app ${sidebarOpen ? "" : "sidebar-hidden"}`}>
      <aside className="sidebar" aria-label="Чаты">
        <div className="sidebar-top">
          <div className="brand"><Logo size={28} /><span className="brand-copy"><strong>|PIVEN.|</strong></span></div>
          <IconButton icon="sidebar" label="Скрыть панель (Ctrl+B)" onClick={() => setSidebarOpen(false)} />
        </div>
        <div className="side-head">
          <span>Чаты</span>
          <button type="button" className="text-btn" onClick={newChat} disabled={state.busy} title="Ctrl+N">+ новый</button>
        </div>
        <label className="search" title="Ctrl+K"><Icon name="search" size={15} /><input ref={searchRef} placeholder="Поиск" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <nav className="chat-nav">
          {pinned.length > 0 && <><div className="nav-caption">Закреплённые</div>{renderRows(pinned)}</>}
          {others.length > 0 && <>{pinned.length > 0 && <div className="nav-caption">Остальные</div>}{renderRows(others)}</>}
          {!filtered.length && <div className="nav-empty">Ничего не найдено</div>}
        </nav>
        <div className="sidebar-bottom">
          <button type="button" className="account" onClick={() => setSettingsOpen(true)}>
            <span className={`dot ${state.models.length ? "ok" : "warn"}`} />
            <span className="account-copy"><strong>Настройки</strong><small>{state.models.length ? `Ollama на связи, моделей: ${state.models.length}` : "Ollama не отвечает"}</small></span>
            <Icon name="settings" size={17} />
          </button>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          {!sidebarOpen && <IconButton icon="sidebar" label="Показать панель (Ctrl+B)" onClick={() => setSidebarOpen(true)} />}
          {!sidebarOpen && <IconButton icon="compose" label="Новый чат (Ctrl+N)" onClick={newChat} disabled={state.busy} />}
          <ModelPicker state={state} api={api} onDone={done} />
          <div className="topbar-title" title={state.chatTitle}>{empty ? "" : state.chatTitle}</div>
          <IconButton icon={resolvedTheme === "light" ? "moon" : "sun"} label={resolvedTheme === "light" ? "Тёмная тема" : "Светлая тема"} onClick={() => setTheme(resolvedTheme === "light" ? "dark" : "light")} />
          <IconButton icon="settings" label="Настройки (Ctrl+,)" onClick={() => setSettingsOpen(true)} />
        </header>

        <Board chatId={state.activeChatId} cards={cards} empty={empty && (
          <div className="welcome">
            <h1>Тут пока пусто</h1>
            <p>Напиши что-нибудь внизу. Ответ появится на доске, карточки можно двигать.</p>
            {recent.length > 0 && (
              <div className="recent">
                <span>Недавние чаты</span>
                {recent.map((chat) => (
                  <button key={chat.id} type="button" onClick={() => { void api.select_chat(chat.id).then((result) => done(result.ok ? undefined : result.error)); }}>
                    {chat.title}<Icon name="arrowRight" size={14} />
                  </button>
                ))}
              </div>
            )}
          </div>
        )} />

        <div className="composer-wrap">
          <Composer api={api} state={state} draft={draft} setDraft={setDraft} onSend={send} onStop={stop} inputRef={inputRef} />
        </div>
      </main>

      {settingsOpen && <SettingsDialog state={state} api={api} theme={theme} setTheme={setTheme} onClose={() => setSettingsOpen(false)} />}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

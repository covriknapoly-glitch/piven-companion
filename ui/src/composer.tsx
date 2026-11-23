import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";
import type { EngineState, ModelFeatures, ModelMemory, ThinkingOptions, ThinkingValue, WebApi } from "./bridge";
import { useImage } from "./cards";
import { SlashMenu, SlashName, SlashUsage, optionMatches, slashArgument, slashCommand, slashMatches, type SlashCommand, type SlashOption, type SlashRow } from "./commands";
import { publishDraft } from "./context";
import { CallControl } from "./dialogs";
import { isPhone } from "./bridge";
import { Icon } from "./icons";
import { FolderChip, ModeChip, nextMode } from "./projects";
import { IconButton, MemoryBadge, ModelLogo, MotionPresence, fileName, groupModels, shortModel, thinkingFixed, thinkingName, useOutsideClose } from "./ui";

const readAsBase64 = (file: File) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(file);
});

/** What the phone's file picker offers: pictures and the files whose text PIVEN can read. */
const PHONE_ACCEPT = "image/*,text/*,.pdf,.docx,.md,.csv,.tsv,.json,.jsonl,.xml,.yaml,.yml,.toml,.ini,.log,.srt,.py,.js,.ts,.tsx,.jsx,.html,.css,"
  + ".java,.kt,.c,.h,.cpp,.hpp,.cs,.go,.rs,.rb,.php,.sql,.sh,.bat,.ps1,.lua,.swift";
const MAX_FILE_BYTES = 20_000_000;
const DRAFTS_KEY = "piven-chat-drafts";

interface ChatDraft { text: string; images: string[]; files: string[] }
const EMPTY_DRAFT: ChatDraft = { text: "", images: [], files: [] };

function readDrafts() {
  const drafts = new Map<string, ChatDraft>();
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(DRAFTS_KEY) ?? "[]");
    if (Array.isArray(saved)) {
      for (const entry of saved) {
        if (Array.isArray(entry) && typeof entry[0] === "string" && typeof entry[1] === "string" && entry[1]) {
          drafts.set(entry[0], { ...EMPTY_DRAFT, text: entry[1] });
        }
      }
    }
  } catch { /* Drafts still work in this window if storage is unavailable. */ }
  return drafts;
}

/** A file waiting above the message field: its name and the kind of document. */
function FileChip({ path, onRemove }: { path: string; onRemove: () => void }) {
  const name = fileName(path);
  const extension = name.includes(".") ? name.split(".").pop()!.toUpperCase().slice(0, 5) : "";
  return (
    <div className="file-chip" title={name}>
      <span className="file-chip-icon"><Icon name="file" size={16} /></span>
      <span className="file-chip-copy"><strong data-i18n-skip>{name}</strong>{extension && <small data-i18n-skip>{extension}</small>}</span>
      <button type="button" aria-label="Убрать файл" onClick={onRemove}><Icon name="close" size={12} /></button>
    </div>
  );
}

function AttachmentChip({ api, path, onRemove }: { api: WebApi; path: string; onRemove: () => void }) {
  const src = useImage(api, path);
  return (
    <div className="attach-chip" title={fileName(path)}>
      {src ? <img src={src} alt="" /> : <span className="attach-chip-empty" />}
      <button type="button" aria-label="Убрать картинку" onClick={onRemove}><Icon name="close" size={12} /></button>
    </div>
  );
}

function ModelMarks({ features }: { features?: ModelFeatures }) {
  if (!features) return null;
  return (
    <span className="model-marks">
      {features.vision && <span title="Видит картинки и экран"><Icon name="image" size={13} /></span>}
      {features.thinking && <span title="Умеет размышлять"><Icon name="spark" size={13} /></span>}
    </span>
  );
}

function ModelChip({ state, api, onDone, onOpenHub, onOpenVoiceHub }: { state: EngineState; api: WebApi; onDone: (error?: string) => void; onOpenHub: () => void; onOpenVoiceHub: () => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const close = useCallback(() => { setOpen(false); setQuery(""); }, []);
  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener("piven:model-menu", show);
    return () => window.removeEventListener("piven:model-menu", show);
  }, []);
  const ref = useOutsideClose(open, close);
  const model = state.settings.model;
  const [memory, setMemory] = useState<ModelMemory | null>(null);
  useEffect(() => { if (open) void api.model_memory().then(setMemory); }, [api, open, state.models]);
  const models = state.models.filter((name) => name.toLowerCase().includes(query.trim().toLowerCase()));
  const groups = groupModels(models);
  const shownModel = shortModel(model);
  return (
    <div className="menu-anchor" ref={ref}>
      <button type="button" className="chip-btn model-chip" onClick={() => setOpen((value) => !value)} title={model || "Модель"}>
        {model && state.models.includes(model) ? <ModelLogo api={api} name={model} size={16} /> : <span className={`status-dot ${state.models.length ? "ok" : "warn"}`} />}

        <span className="chip-text">{model ? shownModel : (state.modelsError ? "Нет моделей" : "Выбрать модель")}</span><Icon name="chevronDown" size={14} />
      </button>
      <MotionPresence>{open && (
        <div className="menu menu-up model-menu" role="menu">
          <div className="menu-search"><Icon name="search" size={15} /><input autoFocus placeholder="Найти модель" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
          <div className="menu-list">
            {groups.map(([title, names]) => [
              groups.length > 1 && <div key={title} className="menu-title">{title}</div>,
              ...names.map((name) => (
                <button key={name} type="button" className={name === model ? "selected" : ""} title={name}
                  onClick={() => { close(); if (name !== model) void api.set_model(name).then((result) => onDone(result.ok ? undefined : result.error)); }}>
                  <ModelLogo api={api} name={name} size={18} /><span className="mono-ish grow model-menu-name" data-i18n-skip>{shortModel(name)}</span>
                  <ModelMarks features={memory?.features?.[name]} /><MemoryBadge estimate={memory?.models[name]} gpu={Math.max(0, (memory?.gpu ?? 0) - (memory?.voiceReserved ?? 0))} context={memory?.context} />{name === model && <Icon name="check" size={15} />}
                </button>
              )),
            ])}
            {!models.length && <div className="menu-empty">{state.models.length ? "Ничего не найдено" : state.modelsError || "Нет моделей"}</div>}
          </div>
          <div className="menu-divider" />
          <button type="button" onClick={() => { close(); void api.refresh_models().then(() => onDone()); }}><Icon name="refresh" size={15} /> Обновить список</button>
          <button type="button" onClick={() => { close(); onOpenHub(); }}><Icon name="download" size={15} /> Скачать модель с Hugging Face…</button>
          <button type="button" onClick={() => { close(); onOpenVoiceHub(); }}><Icon name="mic" size={15} /> Озвучка и распознавание…</button>
        </div>
      )}</MotionPresence>
    </div>
  );
}

const thinkingCache = new WeakMap<WebApi, Map<string, ThinkingOptions>>();

function rememberThinking(api: WebApi, model: string, options: ThinkingOptions) {
  let cache = thinkingCache.get(api);
  if (!cache) { cache = new Map(); thinkingCache.set(api, cache); }
  cache.set(model, options);
}

export async function prefetchThinkingOptions(api: WebApi, state: EngineState) {
  const model = state.settings.model;
  if (!model || !state.models.includes(model)) return;
  const options = await api.thinking_options(model);
  if (!options.error) rememberThinking(api, model, options);
}

function ThinkingChip({ state, api, onDone }: { state: EngineState; api: WebApi; onDone: (error?: string) => void }) {
  const model = state.settings.model;
  const available = Boolean(model) && state.models.includes(model);
  const [options, setOptions] = useState(() => thinkingCache.get(api)?.get(model) ?? null);
  const [open, setOpen] = useState(false);
  const request = useRef(0);
  const close = useCallback(() => setOpen(false), []);
  const ref = useOutsideClose(open, close);
  const refresh = useCallback(async () => {
    const id = ++request.current;
    try {
      const next = await api.thinking_options(model);
      if (id === request.current && !next.error) {
        rememberThinking(api, model, next);
        setOptions(next);
      }
    } catch {
      // Keep the last usable options while the engine is unavailable.
    }
  }, [api, model]);
  useEffect(() => {
    if (available) void refresh();
    return () => { request.current++; };
  }, [available, refresh, state.busy, state.settings.thinkingLevel]);
  if (!options) return null;
  if (!options.values.length) return options.default === true
    ? <span className="chip-btn static" title={thinkingFixed(options)}><Icon name="spark" size={14} /><span className="chip-text">Размышляет</span></span>
    : null;
  const choose = (value: ThinkingValue | "__auto__") => {
    close();
    void api.set_thinking(model, value).then((result) => {
      onDone(result.ok ? undefined : result.error);
      void refresh();
    });
  };

  const effective = options.current === "__auto__" ? options.default ?? options.values[0] : options.current;
  const nameOf = (value: ThinkingValue | null) => (typeof value === "boolean" ? (value ? "С размышлением" : "Без размышления") : thinkingName(value));
  const label = nameOf(effective ?? null);
  return (
    <div className="menu-anchor" ref={ref}>
      <button type="button" className={`chip-btn ${effective === false || effective === "none" ? "off" : ""}`} onClick={() => setOpen((value) => !value)} title="Размышление">
        <Icon name="spark" size={14} /><span className="chip-text">{label}</span><Icon name="chevronDown" size={14} />
      </button>
      <MotionPresence>{open && (
        <div className="menu menu-up" role="menu">
          <div className="menu-label">Размышление</div>
          {options.values.map((value) => (
            <button key={String(value)} type="button" className={String(value) === String(effective) ? "selected" : ""}
              onClick={() => choose(String(value) === String(options.default) ? "__auto__" : value)}>
              <span className="grow">{nameOf(value)}{String(value) === String(options.default) && <small className="menu-hint"> · по умолчанию</small>}</span>
              {String(value) === String(effective) && <Icon name="check" size={15} />}
            </button>
          ))}
        </div>
      )}</MotionPresence>
    </div>
  );
}

export function Composer({ api, state, onSent, onStop, onError, onOpenHub, onOpenVoiceHub, onDraftChats, inputRef, prefill, commands = [] }:
  { api: WebApi; state: EngineState; onSent: (queued: boolean) => void; onStop: () => void; onError: (message?: string) => void; onOpenHub: () => void; onOpenVoiceHub: (kind?: "asr" | "tts") => void;
    onDraftChats: (ids: string[]) => void; inputRef: RefObject<HTMLTextAreaElement | null>; prefill?: { chatId: string; text: string; append?: boolean } | null; commands?: SlashCommand[] }) {
  const chatId = state.activeChatId;
  const [drafts, setDrafts] = useState(readDrafts);
  const chatIds = useMemo(() => new Set(state.chats.map((chat) => chat.id)), [state.chats]);
  const liveChatIds = useRef(chatIds);
  liveChatIds.current = chatIds;
  const changeDraft = useCallback((id: string, change: (value: ChatDraft) => ChatDraft) => {
    setDrafts((current) => {
      if (!liveChatIds.current.has(id)) return current;
      const previous = current.get(id) ?? EMPTY_DRAFT;
      const next = change(previous);
      if (next.text === previous.text && next.images === previous.images && next.files === previous.files) return current;
      const updated = new Map(current);
      if (next.text || next.images.length || next.files.length) updated.set(id, next);
      else updated.delete(id);
      return updated;
    });
  }, []);
  useEffect(() => {
    setDrafts((current) => [...current.keys()].every((id) => chatIds.has(id))
      ? current : new Map([...current].filter(([id]) => chatIds.has(id))));
  }, [chatIds]);
  useEffect(() => {
    const entries = [...drafts].filter(([id]) => liveChatIds.current.has(id));
    const saved = entries.filter(([, entry]) => entry.text).map(([id, entry]) => [id, entry.text]);
    onDraftChats(entries.map(([id]) => id));
    try {
      if (saved.length) localStorage.setItem(DRAFTS_KEY, JSON.stringify(saved));
      else localStorage.removeItem(DRAFTS_KEY);
    } catch { /* Keep the draft in memory if storage is full or blocked. */ }
  }, [drafts, onDraftChats]);

  const { text: draft, images, files } = drafts.get(chatId) ?? EMPTY_DRAFT;
  const setDraft = useCallback((text: string) => changeDraft(chatId, (entry) => ({ ...entry, text })), [changeDraft, chatId]);
  const setImages = (update: (paths: string[]) => string[]) => changeDraft(chatId, (entry) => ({ ...entry, images: update(entry.images) }));
  const setFiles = (update: (paths: string[]) => string[]) => changeDraft(chatId, (entry) => ({ ...entry, files: update(entry.files) }));
  const appliedPrefill = useRef(prefill);
  useEffect(() => { publishDraft(draft); }, [draft]);
  useEffect(() => {
    if (prefill && prefill !== appliedPrefill.current) {
      appliedPrefill.current = prefill;
      changeDraft(prefill.chatId, (entry) => ({ ...entry, text: prefill.append && entry.text.trim() ? `${entry.text.trimEnd()} ${prefill.text}` : prefill.text }));
      if (prefill.chatId === chatId) inputRef.current?.focus();
    }
  }, [prefill, changeDraft, chatId, inputRef]);
  const [dragging, setDragging] = useState(false);
  const dictated = useRef({ session: state.dictation.session, length: state.dictation.text.length, chatId });
  const dictationStart = useRef<string | null>(null);
  const pendingSends = useRef(new Set<string>());
  const phase = state.dictation.phase;
  const wasListening = useRef(false);

  useEffect(() => {
    const { session, text } = state.dictation;
    if (dictated.current.session !== session) {
      dictated.current = { session, length: 0, chatId: dictationStart.current ?? chatId };
      dictationStart.current = null;
    }
    const fresh = text.slice(dictated.current.length).trim();
    dictated.current.length = text.length;
    if (fresh) changeDraft(dictated.current.chatId, (entry) => ({
      ...entry, text: entry.text + (entry.text && !/\s$/.test(entry.text) ? " " : "") + fresh,
    }));
  }, [state.dictation.session, state.dictation.text, chatId, changeDraft]);

  useEffect(() => {
    if (phase === "listening") wasListening.current = true;
    if (!phase && wasListening.current) {
      wasListening.current = false;
      if (!state.dictation.text) onError("Не расслышал, попробуй ещё раз");
    }
  }, [phase]);

  const toggleDictation = () => {
    if (phase) { void api.stop_dictation(); return; }
    if (dictationStart.current) return;
    dictationStart.current = chatId;
    void api.start_dictation().then((reply) => {
      if (!reply.ok) dictationStart.current = null;
      if (!reply.ok && reply.needsModel) { onError("Для голосового ввода нужна модель распознавания речи. Выбери её в этом окне."); onOpenVoiceHub("asr"); }
      else onError(reply.ok ? undefined : reply.error);
    }).catch(() => {
      dictationStart.current = null;
      onError("Не удалось начать запись.");
    });
  };

  const history = useRef<string[]>([]);
  const historyIndex = useRef<number | null>(null);
  const historyDraft = useRef("");

  useEffect(() => {
    const element = inputRef.current;
    if (!element) return;
    element.style.height = "0px";
    element.style.height = `${Math.min(220, element.scrollHeight)}px`;
  }, [draft, inputRef]);

  const photoRef = useRef<HTMLInputElement>(null);
  // Pictures go to the model as pictures; any other file is checked by PIVEN, which keeps it only if it has text to read.
  const addFiles = async (dropped: File[]) => {
    for (const file of dropped) {
      if (file.size > MAX_FILE_BYTES) { onError(`${file.name}: файл больше 20 МБ.`); continue; }
      const picture = file.type.startsWith("image/") && file.type !== "image/svg+xml";
      const data = await readAsBase64(file);
      const result = picture ? await api.save_upload(file.name || "image.png", data) : await api.save_file(file.name, data);
      const add = (current: string[]) => current.includes(result.path!) ? current : [...current, result.path!];
      if (result.ok && result.path) (picture ? setImages : setFiles)(add);
      else onError(result.error);
    }
  };

  // "/" commands: while the name is typed the menu lists commands, after a space it lists the argument's choices
  // (models, themes, …) or shows what the free text is for. The top suggestion is also drawn faintly after the text.
  const named = slashMatches(draft, commands);
  const argument = slashArgument(draft, commands);
  const choosing = argument?.command.options ? argument.command : null;
  const [choices, setChoices] = useState<{ name: string; list: SlashOption[] } | null>(null);
  useEffect(() => {
    if (!choosing?.options) return;
    let live = true;
    const name = choosing.name;
    void Promise.resolve(choosing.options()).then((list) => { if (live) setChoices({ name, list }); }, () => { if (live) setChoices({ name, list: [] }); });
    return () => { live = false; };
  }, [choosing?.name, chatId]);
  const offered = argument && choosing && choices?.name === choosing.name ? optionMatches(argument.arg, choices.list) : null;
  const menu: { title: string; rows: SlashRow[]; fills: string[] } | null = named.length
    ? { title: "Команды", rows: named.map((match) => ({ key: match.command.name, name: <SlashName match={match} />, hint: match.command.hint })),
        fills: named.map((match) => `/${match.word}${match.command.args ? " " : ""}`) }
    : argument && offered
      ? { title: argument.command.hint, rows: offered.map((option) => ({ key: option.value, name: <span className="slash-option">{option.label ?? option.value}</span>, hint: option.hint, current: option.current })),
          fills: offered.map((option) => `/${argument.word} ${option.value}`) }
      : null;
  const usage = !menu && argument && !argument.command.options ? argument : null;
  const [picked, setPicked] = useState("");
  const [slashHidden, setSlashHidden] = useState("");
  useLayoutEffect(() => {
    historyIndex.current = null;
    setDragging(false);
    setPicked("");
    setSlashHidden("");
  }, [chatId]);
  const slashShown = slashHidden !== draft;
  const slashOpen = Boolean(menu) && slashShown;
  let slashActive = menu ? menu.rows.findIndex((row) => row.key === picked) : -1;
  if (menu && slashActive < 0) slashActive = argument?.arg.trim() ? 0 : Math.max(0, menu.rows.findIndex((row) => row.current));
  const fill = slashOpen && menu?.rows.length ? menu.fills[slashActive] : "";
  const ghost = fill.length > draft.length && fill.toLowerCase().startsWith(draft.toLowerCase()) ? fill.slice(draft.length) : "";
  const runCommand = (command: SlashCommand, arg: string, line = draft.trim()) => {
    history.current = [...history.current.filter((item) => item !== line), line].slice(-100);
    historyIndex.current = null;
    setDraft(""); setPicked("");
    command.run(arg);
  };
  const pickRow = (index: number) => {
    const match = named[index];
    if (match) {
      if (match.command.args) { setDraft(`/${match.word} `); setPicked(""); inputRef.current?.focus(); }
      else runCommand(match.command, "", `/${match.word}`);
    } else if (argument && offered?.[index]) runCommand(argument.command, offered[index].value, `/${argument.word} ${offered[index].value}`);
  };

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (pendingSends.current.has(chatId)) return;
    const text = draft.trim();
    if (!text && !images.length && !files.length) return;
    const asked = images.length || files.length ? null : slashCommand(text, commands);
    if (asked) { runCommand(asked.command, asked.arg); return; }
    if (phase) void api.stop_dictation();
    historyIndex.current = null;
    pendingSends.current.add(chatId);
    void api.send_message(text, images, files, chatId).then((result) => {
      if (result.ok) {
        if (text) { history.current = [...history.current.filter((item) => item !== text), text].slice(-100); }
        changeDraft(chatId, (entry) => ({
          text: entry.text === draft ? "" : entry.text,
          images: images.length ? entry.images.filter((item) => !images.includes(item)) : entry.images,
          files: files.length ? entry.files.filter((item) => !files.includes(item)) : entry.files,
        }));
        onSent(Boolean(result.queued));
      } else onError(result.error);
    }).catch(() => onError("Не удалось отправить сообщение.")).finally(() => pendingSends.current.delete(chatId));
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (slashOpen && menu) {
      const count = menu.rows.length;
      if ((event.key === "ArrowDown" || event.key === "ArrowUp") && count) {
        event.preventDefault();
        setPicked(menu.rows[(slashActive + (event.key === "ArrowDown" ? 1 : count - 1)) % count].key);
        return;
      }
      const atEnd = event.currentTarget.selectionStart === draft.length;
      if (fill && ((event.key === "Tab" && !event.shiftKey) || (event.key === "ArrowRight" && ghost && atEnd))) { event.preventDefault(); setDraft(fill); return; }
      if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && count) { event.preventDefault(); pickRow(slashActive); return; }
    }
    if ((slashOpen || usage) && slashShown && event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setSlashHidden(draft); return; }
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); return; }
    if (event.key === "Tab" && event.shiftKey && state.code.on) { event.preventDefault(); void api.code_set({ mode: nextMode(state.code.mode) }).then((result) => onError(result.ok ? undefined : result.error)); return; }
    const caretAtStart = event.currentTarget.selectionStart === 0 && event.currentTarget.selectionEnd === 0;
    if (event.key === "ArrowUp" && history.current.length && (caretAtStart || !draft.includes("\n"))) {
      event.preventDefault();
      if (historyIndex.current === null) { historyDraft.current = draft; historyIndex.current = history.current.length; }
      historyIndex.current = Math.max(0, historyIndex.current - 1);
      setDraft(history.current[historyIndex.current]);
    } else if (event.key === "ArrowDown" && historyIndex.current !== null) {
      event.preventDefault();
      historyIndex.current += 1;
      if (historyIndex.current >= history.current.length) { historyIndex.current = null; setDraft(historyDraft.current); }
      else setDraft(history.current[historyIndex.current]);
    }
  };

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const pasted = Array.from(event.clipboardData.files);
    if (pasted.length) { event.preventDefault(); void addFiles(pasted); }
  };
  const onDrop = (event: DragEvent) => { event.preventDefault(); setDragging(false); void addFiles(Array.from(event.dataTransfer.files)); };

  const canSend = Boolean(draft.trim() || images.length || files.length);
  return (
    <form className={`composer ${dragging ? "is-dragging" : ""}`} onSubmit={submit}
      onDragOver={(event) => { if (event.dataTransfer.types.includes("Files")) { event.preventDefault(); setDragging(true); } }}
      onDragLeave={() => setDragging(false)} onDrop={onDrop}>
      {(images.length > 0 || files.length > 0) && (
        <div className="composer-attachments">
          {images.map((path) => <AttachmentChip key={path} api={api} path={path} onRemove={() => setImages((current) => current.filter((item) => item !== path))} />)}
          {files.map((path) => <FileChip key={path} path={path} onRemove={() => setFiles((current) => current.filter((item) => item !== path))} />)}
        </div>
      )}
      <MotionPresence>{slashOpen && menu && <SlashMenu title={menu.title} rows={menu.rows} active={slashActive} empty="Нет подходящих вариантов" onPick={pickRow} />}</MotionPresence>
      <MotionPresence>{usage && slashShown && <SlashUsage command={usage.command} word={usage.word} />}</MotionPresence>
      <div className="composer-input">
        {ghost && <div className="composer-ghost" aria-hidden="true" data-i18n-skip><span>{draft}</span>{ghost}</div>}
        <textarea ref={inputRef} rows={1} aria-label="Сообщение" value={draft} spellCheck
          placeholder={phase === "listening" ? "Говори, текст появится здесь" : phase === "starting" ? "Запускает распознавание" : state.busy ? "Можно дописать: сообщение учтётся в работе" : "Сообщение или / для команд"}
          onChange={(event) => setDraft(event.target.value)} onKeyDown={onKeyDown} onPaste={onPaste} />
      </div>
      <div className="composer-bar">
        <IconButton icon="paperclip" label="Прикрепить картинку или файл (можно вставить Ctrl+V или перетащить)"
          onClick={() => {
            if (isPhone) { photoRef.current?.click(); return; }
            void api.pick_attachments().then((picked) => {
              setImages((current) => [...current, ...picked.images.filter((path) => !current.includes(path))]);
              setFiles((current) => [...current, ...picked.files.filter((path) => !current.includes(path))]);
              if (picked.error) onError(picked.error);
            });
          }} />
        {isPhone && <input ref={photoRef} type="file" accept={PHONE_ACCEPT} multiple hidden onChange={(event) => { const files = [...(event.target.files ?? [])]; event.target.value = ""; void addFiles(files); }} />}
        <ModelChip state={state} api={api} onDone={onError} onOpenHub={onOpenHub} onOpenVoiceHub={onOpenVoiceHub} />
        <ThinkingChip key={state.settings.model} state={state} api={api} onDone={onError} />
        <span className="composer-spacer" />
        {state.code.on && <FolderChip state={state} api={api} onDone={onError} />}
        {state.code.on && <ModeChip state={state} api={api} onDone={onError} />}
        {!isPhone && !state.listening.running && !state.settings.heavyMode && (
          <button type="button" className={`call-btn mic-btn ${phase ? "on" : ""}`} disabled={phase === "recognizing"} aria-pressed={Boolean(phase)} onClick={toggleDictation}
            title={phase === "recognizing" ? "Распознаёт речь" : phase ? "Остановить запись" : "Голосовой ввод"} aria-label={phase ? "Остановить запись" : "Голосовой ввод"}>
            {phase === "recognizing" ? <span className="spinner" /> : <Icon name="mic" size={16} />}
          </button>
        )}
        {!isPhone && !state.settings.heavyMode && <CallControl api={api} state={state} onError={onError} />}
        {state.busy && <button type="button" className="send-btn stop" onClick={onStop} title="Остановить (Esc)" aria-label="Остановить"><Icon name="stop" size={15} /></button>}
        {(!state.busy || canSend) && <button type="submit" className="send-btn" disabled={!canSend} title="Отправить (Enter)" aria-label="Отправить"><Icon name="arrowUp" size={18} /></button>}
      </div>
      {dragging && <div className="drop-hint"><Icon name="image" size={20} /> Отпусти, чтобы прикрепить картинку</div>}
    </form>
  );
}

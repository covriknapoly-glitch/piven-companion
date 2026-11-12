import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";
import type { EngineState, ModelFeatures, ModelMemory, ThinkingOptions, ThinkingValue, WebApi } from "./bridge";
import { useImage } from "./cards";
import { publishDraft } from "./context";
import { CallControl } from "./dialogs";
import { isPhone } from "./bridge";
import { Icon } from "./icons";
import { FolderChip, ModeChip, nextMode } from "./projects";
import { IconButton, MemoryBadge, ModelLogo, fileName, groupModels, shortModel, thinkingFixed, thinkingName, useOutsideClose } from "./ui";

const readAsBase64 = (file: File) => new Promise<string>((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
  reader.onerror = () => reject(reader.error);
  reader.readAsDataURL(file);
});

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
      {open && (
        <div className="menu menu-up model-menu" role="menu">
          <div className="menu-search"><Icon name="search" size={15} /><input autoFocus placeholder="Найти модель" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
          <div className="menu-list">
            {groups.map(([title, names]) => [
              groups.length > 1 && <div key={title} className="menu-title">{title}</div>,
              ...names.map((name) => (
                <button key={name} type="button" className={name === model ? "selected" : ""} title={name}
                  onClick={() => { close(); if (name !== model) void api.set_model(name).then((result) => onDone(result.ok ? undefined : result.error)); }}>
                  <ModelLogo api={api} name={name} size={18} /><span className="mono-ish grow">{shortModel(name)}</span>
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
      )}
    </div>
  );
}

function ThinkingChip({ state, api, onDone }: { state: EngineState; api: WebApi; onDone: (error?: string) => void }) {
  const model = state.settings.model;
  const [options, setOptions] = useState<ThinkingOptions | null>(null);
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useOutsideClose(open, close);
  useEffect(() => {
    setOptions(null);
    if (model && state.models.includes(model)) void api.thinking_options(model).then(setOptions);
  }, [api, model, state.models]);
  useEffect(() => {
    if (!state.busy && model && state.models.includes(model)) void api.thinking_options(model).then(setOptions);
  }, [state.busy]);
  if (!options || options.error) return null;
  if (!options.values.length) return options.default === true
    ? <span className="chip-btn static" title={thinkingFixed(options)}><Icon name="spark" size={14} /><span className="chip-text">Размышляет</span></span>
    : null;
  const choose = (value: ThinkingValue | "__auto__") => {
    close();
    void api.set_thinking(model, value).then((result) => {
      onDone(result.ok ? undefined : result.error);
      void api.thinking_options(model).then(setOptions);
    });
  };

  const effective = options.current === "__auto__" ? options.default ?? options.values[0] : options.current;

  if (options.values.every((value) => typeof value === "boolean")) {
    const next = !effective;
    return (
      <button type="button" className={`chip-btn ${effective ? "" : "off"}`} aria-pressed={Boolean(effective)} title="Размышление: нажми, чтобы переключить"
        onClick={() => choose(next === options.default ? "__auto__" : next)}>
        <Icon name="spark" size={14} /><span className="chip-text">{effective ? "С размышлением" : "Без размышления"}</span>
      </button>
    );
  }
  const label = typeof effective === "boolean" ? (effective ? "С размышлением" : "Без размышления") : thinkingName(effective ?? null);
  return (
    <div className="menu-anchor" ref={ref}>
      <button type="button" className="chip-btn" onClick={() => setOpen((value) => !value)} title="Размышление">
        <Icon name="spark" size={14} /><span className="chip-text">{label}</span><Icon name="chevronDown" size={14} />
      </button>
      {open && (
        <div className="menu menu-up" role="menu">
          <div className="menu-label">Размышление</div>
          {options.values.map((value) => (
            <button key={String(value)} type="button" className={String(value) === String(effective) ? "selected" : ""}
              onClick={() => choose(String(value) === String(options.default) ? "__auto__" : value)}>
              <span className="grow">{thinkingName(value)}{String(value) === String(options.default) && <small className="menu-hint"> · по умолчанию</small>}</span>
              {String(value) === String(effective) && <Icon name="check" size={15} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Composer({ api, state, onSent, onStop, onError, onOpenHub, onOpenVoiceHub, inputRef, prefill }:
  { api: WebApi; state: EngineState; onSent: (queued: boolean) => void; onStop: () => void; onError: (message?: string) => void; onOpenHub: () => void; onOpenVoiceHub: (kind?: "asr" | "tts") => void;
    inputRef: RefObject<HTMLTextAreaElement | null>; prefill?: { text: string; nonce: number } | null }) {
  const [draft, setDraft] = useState("");
  useEffect(() => { publishDraft(draft); }, [draft]);
  useEffect(() => { if (prefill) { setDraft(prefill.text); inputRef.current?.focus(); } }, [prefill, inputRef]);
  const [images, setImages] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const dictated = useRef({ session: state.dictation.session, length: state.dictation.text.length });
  const phase = state.dictation.phase;
  const wasListening = useRef(false);

  useEffect(() => {
    const { session, text } = state.dictation;
    if (dictated.current.session !== session) dictated.current = { session, length: 0 };
    const fresh = text.slice(dictated.current.length).trim();
    dictated.current.length = text.length;
    if (fresh) setDraft((current) => (current && !/\s$/.test(current) ? `${current} ${fresh}` : current + fresh));
  }, [state.dictation.session, state.dictation.text]);

  useEffect(() => {
    if (phase === "listening") wasListening.current = true;
    if (!phase && wasListening.current) {
      wasListening.current = false;
      if (!state.dictation.text) onError("Не расслышал, попробуй ещё раз");
    }
  }, [phase]);

  const toggleDictation = () => {
    if (phase) { void api.stop_dictation(); return; }
    void api.start_dictation().then((reply) => {
      if (!reply.ok && reply.needsModel) { onError("Для голосового ввода нужна модель распознавания речи. Выбери её в этом окне."); onOpenVoiceHub("asr"); }
      else onError(reply.ok ? undefined : reply.error);
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
  const addFiles = async (files: File[]) => {
    for (const file of files.filter((item) => item.type.startsWith("image/"))) {
      const result = await api.save_upload(file.name || "image.png", await readAsBase64(file));
      if (result.ok && result.path) setImages((current) => current.includes(result.path!) ? current : [...current, result.path!]);
      else onError(result.error);
    }
  };

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    const text = draft.trim();
    if (!text && !images.length) return;
    if (phase) void api.stop_dictation();
    void api.send_message(text, images).then((result) => {
      if (result.ok) {
        if (text) { history.current = [...history.current.filter((item) => item !== text), text].slice(-100); }
        historyIndex.current = null;
        setDraft(""); setImages([]);
        onSent(Boolean(result.queued));
      } else onError(result.error);
    });
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
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
    const files = Array.from(event.clipboardData.files);
    if (files.some((file) => file.type.startsWith("image/"))) { event.preventDefault(); void addFiles(files); }
  };
  const onDrop = (event: DragEvent) => { event.preventDefault(); setDragging(false); void addFiles(Array.from(event.dataTransfer.files)); };

  const canSend = Boolean(draft.trim() || images.length);
  return (
    <form className={`composer ${dragging ? "is-dragging" : ""}`} onSubmit={submit}
      onDragOver={(event) => { if (event.dataTransfer.types.includes("Files")) { event.preventDefault(); setDragging(true); } }}
      onDragLeave={() => setDragging(false)} onDrop={onDrop}>
      {images.length > 0 && (
        <div className="composer-attachments">
          {images.map((path) => <AttachmentChip key={path} api={api} path={path} onRemove={() => setImages((current) => current.filter((item) => item !== path))} />)}
        </div>
      )}
      <textarea ref={inputRef} rows={1} aria-label="Сообщение" value={draft} spellCheck
        placeholder={phase === "listening" ? "Говори, текст появится здесь" : phase === "starting" ? "Запускает распознавание" : state.busy ? "Можно дописать: сообщение учтётся в работе" : "Сообщение"}
        onChange={(event) => setDraft(event.target.value)} onKeyDown={onKeyDown} onPaste={onPaste} />
      <div className="composer-bar">
        <IconButton icon="paperclip" label="Прикрепить картинку (можно вставить Ctrl+V или перетащить)"
          onClick={() => { if (isPhone) { photoRef.current?.click(); return; } void api.pick_images().then((paths) => setImages((current) => [...current, ...paths.filter((path) => !current.includes(path))])); }} />
        {isPhone && <input ref={photoRef} type="file" accept="image/*" multiple hidden onChange={(event) => { const files = [...(event.target.files ?? [])]; event.target.value = ""; void addFiles(files); }} />}
        <ModelChip state={state} api={api} onDone={onError} onOpenHub={onOpenHub} onOpenVoiceHub={onOpenVoiceHub} />
        <ThinkingChip state={state} api={api} onDone={onError} />
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

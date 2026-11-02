import { useCallback, useEffect, useRef, useState, type ClipboardEvent, type DragEvent, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";
import type { EngineState, ModelMemory, ThinkingOptions, ThinkingValue, WebApi } from "./bridge";
import { useImage } from "./cards";
import { CallControl } from "./dialogs";
import { Icon } from "./icons";
import { IconButton, MemoryBadge, ModelLogo, fileName, thinkingFixed, thinkingName, useOutsideClose } from "./ui";

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

function ModelChip({ state, api, onDone, onOpenHub, onOpenVoiceHub }: { state: EngineState; api: WebApi; onDone: (error?: string) => void; onOpenHub: () => void; onOpenVoiceHub: () => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const close = useCallback(() => { setOpen(false); setQuery(""); }, []);
  const ref = useOutsideClose(open, close);
  const model = state.settings.model;
  const [memory, setMemory] = useState<ModelMemory | null>(null);
  useEffect(() => { if (open) void api.model_memory().then(setMemory); }, [api, open, state.models]);
  const models = state.models.filter((name) => name.toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <div className="menu-anchor" ref={ref}>
      <button type="button" className="chip-btn" disabled={state.busy} onClick={() => setOpen((value) => !value)} title={model || "Модель"}>
        {model && state.models.includes(model) ? <ModelLogo api={api} name={model} size={16} /> : <span className={`status-dot ${state.models.length ? "ok" : "warn"}`} />}
        {/* only the start of the file name; the whole name is in the tooltip and the menu */}
        <span className="chip-text">{model ? (model.length > 10 ? `${model.slice(0, 10)}…` : model) : (state.modelsError ? "Нет моделей" : "Выбрать модель")}</span>
        <Icon name="chevronDown" size={14} />
      </button>
      {open && (
        <div className="menu menu-up model-menu" role="menu">
          <div className="menu-search"><Icon name="search" size={15} /><input autoFocus placeholder="Найти модель" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
          <div className="menu-list">
            {models.map((name) => (
              <button key={name} type="button" className={name === model ? "selected" : ""}
                onClick={() => { close(); if (name !== model) void api.set_model(name).then((result) => onDone(result.ok ? undefined : result.error)); }}>
                <ModelLogo api={api} name={name} size={18} /><span className="mono-ish grow">{name}</span><MemoryBadge estimate={memory?.models[name]} gpu={Math.max(0, (memory?.gpu ?? 0) - (memory?.voiceReserved ?? 0))} context={memory?.context} />{name === model && <Icon name="check" size={15} />}
              </button>
            ))}
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

/** The model's thinking mode next to the model chip; a fixed note for models that cannot switch it. */
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
  // "auto" means the model's default: the menu shows that default as the chosen mode instead of a separate item
  const effective = options.current === "__auto__" ? options.default ?? options.values[0] : options.current;
  // the chip says what the model will do: think or not, or how deeply
  const label = typeof effective === "boolean" ? (effective ? "С размышлением" : "Без размышления") : `Размышление: ${thinkingName(effective ?? null).toLowerCase()}`;
  return (
    <div className="menu-anchor" ref={ref}>
      <button type="button" className="chip-btn" disabled={state.busy} onClick={() => setOpen((value) => !value)} title="Размышление">
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
  { api: WebApi; state: EngineState; onSent: (queued: boolean) => void; onStop: () => void; onError: (message?: string) => void; onOpenHub: () => void; onOpenVoiceHub: () => void;
    inputRef: RefObject<HTMLTextAreaElement | null>; prefill?: { text: string; nonce: number } | null }) {
  const [draft, setDraft] = useState("");
  useEffect(() => { if (prefill) { setDraft(prefill.text); inputRef.current?.focus(); } }, [prefill, inputRef]);
  const [images, setImages] = useState<string[]>([]);
  const [hint, setHint] = useState("");
  const [dragging, setDragging] = useState(false);
  const history = useRef<string[]>([]);
  const historyIndex = useRef<number | null>(null);
  const historyDraft = useRef("");

  useEffect(() => {
    const text = draft.trim();
    if (!text || images.length) { setHint(images.length ? "спросит про картинку" : ""); return; }
    const timer = window.setTimeout(() => { void api.route_hint(text).then((result) => setHint(result.label)); }, 160);
    return () => window.clearTimeout(timer);
  }, [api, draft, images.length]);

  useEffect(() => {
    const element = inputRef.current;
    if (!element) return;
    element.style.height = "0px";
    element.style.height = `${Math.min(220, element.scrollHeight)}px`;
  }, [draft, inputRef]);

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
        placeholder={state.busy ? "Отправится после текущего ответа" : "Сообщение"}
        onChange={(event) => setDraft(event.target.value)} onKeyDown={onKeyDown} onPaste={onPaste} />
      <div className="composer-bar">
        <IconButton icon="paperclip" label="Прикрепить картинку (можно вставить Ctrl+V или перетащить)"
          onClick={() => { void api.pick_images().then((paths) => setImages((current) => [...current, ...paths.filter((path) => !current.includes(path))])); }} />
        <ModelChip state={state} api={api} onDone={onError} onOpenHub={onOpenHub} onOpenVoiceHub={onOpenVoiceHub} />
        <ThinkingChip state={state} api={api} onDone={onError} />
        {hint && <span className="route-hint"><Icon name="spark" size={13} />{hint}</span>}
        <span className="composer-spacer" />
        <CallControl api={api} state={state} onError={onError} />
        {state.busy && !canSend
          ? <button type="button" className="send-btn stop" onClick={onStop} title="Остановить (Esc)" aria-label="Остановить"><Icon name="stop" size={15} /></button>
          : <button type="submit" className="send-btn" disabled={!canSend} title="Отправить (Enter)" aria-label="Отправить"><Icon name="arrowUp" size={18} /></button>}
      </div>
      {dragging && <div className="drop-hint"><Icon name="image" size={20} /> Отпусти, чтобы прикрепить картинку</div>}
    </form>
  );
}

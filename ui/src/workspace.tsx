import { useCallback, useEffect, useMemo, useState } from "react";
import type { CodeFile, EngineState, Slide, WebApi } from "./bridge";
import { BrowserPane } from "./browser";
import { useImage } from "./cards";
import { ContextTab } from "./context";
import { Icon } from "./icons";
import { Button, Decor, IconButton, SelectionMarker, fileName } from "./ui";

export type WorkspaceTab = "browser" | "files" | "context";

export function Workspace({ api, state, tab, setTab, browserRequest, covered, onReference }:
  { api: WebApi; state: EngineState; tab: WorkspaceTab; setTab: (tab: WorkspaceTab) => void; browserRequest: { url: string; nonce: number } | null;
    covered: boolean; onReference: (path: string) => void }) {
  const [attachments, setAttachments] = useState(false);
  const project = Boolean(state.code.on || state.code.root);
  const fileTab = project && !attachments ? "project" : "attachments";
  return (
    <div className="workspace-body">
      <div className="workspace-tabs" role="tablist">
        <SelectionMarker selected={tab} />
        {([["browser", "Браузер", "external"], ["files", "Файлы", "folder"], ["context", "Контекст", "database"]] as const).map(([id, label, icon]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>
            <Icon name={icon} size={14} />{label}
          </button>
        ))}
      </div>

      <div className="workspace-slot workspace-content">
        <div className={`workspace-slot workspace-browser ${tab === "browser" ? "tab-view" : ""}`} inert={tab !== "browser"}>
          <BrowserPane api={api} openRequest={browserRequest} covered={covered || tab !== "browser"} />
        </div>
        {tab === "files" && project && <div className="files-bar project-file-tabs" role="tablist" aria-label="Файлы и вложения">
          <SelectionMarker selected={fileTab} />
          <button type="button" role="tab" aria-selected={!attachments} aria-controls="workspace-file-view"
            className={attachments ? "" : "on"} onClick={() => setAttachments(false)}>Проект</button>
          <button type="button" role="tab" aria-selected={attachments} aria-controls="workspace-file-view"
            className={attachments ? "on" : ""} onClick={() => setAttachments(true)}>Вложения</button>
        </div>}
        {tab === "files" && <div key={fileTab} id="workspace-file-view" className="workspace-slot tab-view" role={project ? "tabpanel" : undefined}>
          {fileTab === "project"
            ? <ProjectFiles key={JSON.stringify([state.activeChatId, state.code.root])} api={api} state={state} onReference={onReference} />
            : <FilesTab api={api} state={state} />}
        </div>}
        {tab === "context" && <div className="workspace-slot tab-view"><ContextTab api={api} state={state} /></div>}
      </div>
    </div>
  );
}

const IMAGE = /\.(png|jpe?g|webp|bmp|gif)$/i;
const VIDEO = /\.(mp4|webm|mkv)$/i;

function ProjectFiles({ api, state, onReference }: { api: WebApi; state: EngineState; onReference: (path: string) => void }) {
  const chatId = state.activeChatId;
  const [listing, setListing] = useState<{ root: string; files: CodeFile[]; limited?: boolean } | null>(null);
  const [folder, setFolder] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("");
  const [preview, setPreview] = useState<Awaited<ReturnType<WebApi["code_read"]>> | null>(null);
  const [memory, setMemory] = useState<Awaited<ReturnType<WebApi["code_project_memory"]>> | null>(null);
  const [memoryError, setMemoryError] = useState("");
  const [error, setError] = useState("");
  const refreshFiles = useCallback(() => api.code_files(chatId).then((result) => {
    setListing(result); setError("");
  }).catch(() => setError("Не удалось открыть файлы проекта.")), [api, chatId]);
  const refreshMemory = useCallback(async (action?: "refresh" | "forget", entry?: number) => {
    try {
      const reply = await api.code_project_memory(chatId, action, entry);
      if (reply.ok) { setMemory(reply); setMemoryError(""); }
      else setMemoryError(reply.error || "Память проекта недоступна.");
    } catch { setMemoryError("Память проекта недоступна."); }
  }, [api, chatId]);
  useEffect(() => { if (state.code.root) void refreshFiles(); }, [state.busy, state.code.root, refreshFiles]);
  useEffect(() => {
    if (!state.code.root) return;
    void refreshMemory();
    const timer = window.setInterval(() => { void refreshMemory(); }, 2000);
    return () => window.clearInterval(timer);
  }, [state.code.root, refreshMemory]);
  useEffect(() => {
    if (!selected) return;
    let current = true;
    setPreview(null);
    void api.code_read(selected, chatId).then((reply) => { if (current) setPreview(reply); })
      .catch(() => { if (current) setPreview({ ok: false, error: "Не удалось прочитать файл." }); });
    return () => { current = false; };
  }, [api, chatId, selected, listing]);
  const needle = query.trim().toLowerCase();
  const files = (listing?.files ?? []).filter((item) =>
    needle ? item.path.toLowerCase().includes(needle) : item.path.slice(0, Math.max(0, item.path.lastIndexOf("/"))) === folder);
  const visibleFiles = files.sort((a,b) => Number(b.directory) - Number(a.directory) || a.path.localeCompare(b.path));
  const parent = folder.split("/").slice(0, -1).join("/");
  const index = memory?.index;

  if (!state.code.root || listing?.root === "") return <div className="project-no-folder">
    <p>Выбери папку, чтобы открыть файлы проекта.</p>
    <Button icon="folder" onClick={() => { void api.code_pick_folder(); }}>Выбрать папку…</Button>
  </div>;
  if (selected) return <div className="workspace-slot files-view">
    <div className="files-bar">
      <IconButton icon="arrowRight" className="flip-x" label="К списку файлов" onClick={() => setSelected("")} />
      <strong title={selected} data-i18n-skip>{selected}</strong>
      <span className="topbar-spacer" />
      <Button kind="ghost" onClick={() => onReference(selected)}>Указать в чате</Button>
    </div>
    {!preview ? <p className="pane-note files-empty">Загрузка…</p> : preview.ok ?
      <><pre className="project-source" data-i18n-skip>{preview.text}</pre>{preview.truncated && <p className="pane-note files-empty">Показано начало файла.</p>}</>
      : <p className="pane-note files-empty">{preview.error}</p>}
  </div>;
  return <div className="workspace-slot files-list">
    <div className="files-bar">
      {folder && <IconButton icon="arrowRight" className="flip-x" label="На уровень выше" onClick={() => { setFolder(parent); setQuery(""); }} />}
      <strong title={listing?.root} data-i18n-skip>{folder || fileName(listing?.root || state.code.root)}</strong>
      <span className="topbar-spacer" />
      <IconButton icon="folder" label="Открыть папку проекта" onClick={() => { void api.code_open_folder(); }} />
      <IconButton icon="refresh" label="Обновить список" onClick={() => { void refreshFiles(); }} />
    </div>
    <input className="input project-file-search" aria-label="Найти файл проекта" placeholder="Найти файл проекта" value={query} onChange={(event) => setQuery(event.target.value)} />
    <details className="project-memory">
      <summary>Память проекта</summary>
      {index && <p className="pane-note">{index.indexing ? "Индексирует документы…" : `Документов в индексе: ${index.files}`}</p>}
      {(memoryError || index?.error) && <p className="pane-note">{memoryError || index?.error}</p>}
      <Button kind="ghost" icon="refresh" disabled={index?.indexing} onClick={() => { void refreshMemory("refresh"); }}>Обновить индекс</Button>
      {memory?.notes?.length === 0 && <p className="pane-note">Пока нет заметок проекта.</p>}
      {memory?.notes?.map((note) => <div className="memory-fact" key={note.id}>
        <div className="memory-fact-body" data-i18n-skip>{note.text}</div>
        <IconButton icon="close" label="Забыть" onClick={() => { void refreshMemory("forget", note.id); }} />
      </div>)}
    </details>
    {error && <p className="pane-note files-empty">{error}</p>}
    {!listing && !error && <p className="pane-note files-empty">Загрузка…</p>}
    {listing && !visibleFiles.length && <p className="pane-note files-empty">{needle ? "Ничего не найдено" : "Файлов пока нет"}</p>}
    {listing?.limited && <p className="pane-note files-empty">Показана часть файлов проекта.</p>}
    {visibleFiles.map((file) => <button key={file.path} type="button" className="file-row" title={file.path}
      onClick={() => { if (file.directory) { setFolder(file.path); setQuery(""); } else setSelected(file.path); }}>
      <Icon name={file.directory ? "folder" : "file"} size={16} />
      <span className="file-name" data-i18n-skip>{needle ? file.path : fileName(file.path)}</span>
    </button>)}
  </div>;
}

function FilesTab({ api, state }: { api: WebApi; state: EngineState }) {
  const files = useMemo(() => {
    const seen = new Set<string>();
    const list: string[] = [];
    [...state.items].reverse().forEach((item) => [...item.images, ...(item.files ?? [])].forEach((path) => { if (!seen.has(path)) { seen.add(path); list.push(path); } }));
    return list;
  }, [state.items]);
  const [open, setOpen] = useState("");
  useEffect(() => { if (open && !files.includes(open)) setOpen(""); }, [files, open]);
  if (open) return (
    <div className="workspace-slot files-view">
      <div className="files-bar">
        <IconButton icon="arrowRight" className="flip-x" label="К списку файлов" size={15} onClick={() => setOpen("")} />
        <strong title={open}>{fileName(open)}</strong>
        <span className="topbar-spacer" />
        <Button kind="ghost" icon="external" onClick={() => { void api.open_file(open); }}>Открыть в программе</Button>
      </div>
      {IMAGE.test(open) ? <ImageView api={api} path={open} /> : VIDEO.test(open) ? <ImageView api={api} path={open} video />
        : /\.pptx$/i.test(open) ? <SlidesView api={api} path={open} />
        : <p className="pane-note files-empty">Этот файл не показывается в программе. Открой его кнопкой выше.</p>}
    </div>
  );
  return (
    <div className="workspace-slot files-list">
      {!files.length && <div className="attachments-empty"><Decor corner="br" /><p className="pane-note">Файлов пока нет</p></div>}
      {files.map((path) => (
        <button key={path} type="button" className="file-row" onClick={() => setOpen(path)} title={path}>
          {IMAGE.test(path) ? <Thumb api={api} path={path} /> : <span className="file-icon"><Icon name={/\.pptx$/i.test(path) ? "presentation" : VIDEO.test(path) ? "play" : "file"} size={18} /></span>}
          <span className="file-name">{fileName(path)}</span>
        </button>
      ))}
    </div>
  );
}

function Thumb({ api, path }: { api: WebApi; path: string }) {
  const src = useImage(api, path);
  return src ? <img className="file-thumb" src={src} alt="" /> : <span className="file-icon"><Icon name="image" size={18} /></span>;
}

function ImageView({ api, path, video = false }: { api: WebApi; path: string; video?: boolean }) {
  const src = useImage(api, path);
  if (!src) return <div className="files-image"><p className="pane-note">Загрузка…</p></div>;
  return <div className="files-image">{video ? <video src={src} controls loop /> : <img src={src} alt={fileName(path)} />}</div>;
}

function SlidesView({ api, path }: { api: WebApi; path: string }) {
  const [slides, setSlides] = useState<Slide[] | null>(null);
  const [error, setError] = useState("");
  const [index, setIndex] = useState(0);
  useEffect(() => {
    setSlides(null); setIndex(0);
    void api.presentation_slides(path).then((reply) => { if (reply.ok) setSlides(reply.slides); else setError(reply.error ?? "Не удалось прочитать презентацию."); });
  }, [api, path]);
  if (error) return <p className="pane-note files-empty">{error}</p>;
  if (!slides) return <p className="pane-note files-empty">Загрузка…</p>;
  const slide = slides[index];
  const dark = isDark(slide.background);
  return (
    <div className="slides">
      <div className={`slide ${dark ? "dark" : ""}`} style={slide.background ? { background: slide.background } : undefined}
        tabIndex={0} onKeyDown={(event) => { if (event.key === "ArrowRight") setIndex((value) => Math.min(slides.length - 1, value + 1)); if (event.key === "ArrowLeft") setIndex((value) => Math.max(0, value - 1)); }}>
        {slide.title && <h3>{slide.title}</h3>}
        <div className="slide-body">
          {slide.texts.length > 0 && <ul>{slide.texts.map((text, key) => <li key={key}>{text}</li>)}</ul>}
          {slide.images.map((src, key) => <img key={key} src={src} alt="" />)}
        </div>
      </div>
      <div className="slides-nav">
        <IconButton icon="arrowRight" className="flip-x" label="Предыдущий слайд" disabled={index === 0} onClick={() => setIndex(index - 1)} />
        <span>{index + 1} / {slides.length}</span>
        <IconButton icon="arrowRight" label="Следующий слайд" disabled={index === slides.length - 1} onClick={() => setIndex(index + 1)} />
      </div>
      <div className="slides-strip">
        {slides.map((item, key) => (
          <button key={key} type="button" className={key === index ? "on" : ""} onClick={() => setIndex(key)}>{key + 1}. {item.title || "без заголовка"}</button>
        ))}
      </div>
    </div>
  );
}

function isDark(color: string) {
  const match = /^#?([0-9a-f]{6})$/i.exec(color || "");
  if (!match) return false;
  const value = parseInt(match[1], 16);
  return ((value >> 16) * 299 + ((value >> 8) & 255) * 587 + (value & 255) * 114) / 1000 < 128;
}

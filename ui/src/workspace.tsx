import { useEffect, useMemo, useState } from "react";
import type { EngineState, Slide, WebApi } from "./bridge";
import { BrowserPane } from "./browser";
import { useImage } from "./cards";
import { ContextTab } from "./context";
import { Icon } from "./icons";
import { Button, Decor, IconButton, fileName } from "./ui";

export type WorkspaceTab = "browser" | "files" | "context";

export function Workspace({ api, state, tab, setTab, browserRequest, covered, onClose }:
  { api: WebApi; state: EngineState; tab: WorkspaceTab; setTab: (tab: WorkspaceTab) => void; browserRequest: { url: string; nonce: number } | null;
    covered: boolean; onClose: () => void }) {
  return (
    <div className="workspace-body">
      <div className="workspace-tabs" role="tablist">
        {([["browser", "Браузер", "external"], ["files", "Файлы", "folder"], ["context", "Контекст", "database"]] as const).map(([id, label, icon]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>
            <Icon name={icon} size={14} />{label}
          </button>
        ))}
        <span className="topbar-spacer" />
        <IconButton icon="workspace" label="Скрыть панель (Ctrl+D)" onClick={onClose} />
      </div>

      <div className={tab === "browser" ? "workspace-slot" : "workspace-hidden"}>
        <BrowserPane api={api} openRequest={browserRequest} covered={covered || tab !== "browser"} />
      </div>
      {tab === "files" && <FilesTab api={api} state={state} />}
      {tab === "context" && <ContextTab api={api} state={state} />}
    </div>
  );
}

const IMAGE = /\.(png|jpe?g|webp|bmp|gif)$/i;
const VIDEO = /\.(mp4|webm|mkv)$/i;

function FilesTab({ api, state }: { api: WebApi; state: EngineState }) {
  const files = useMemo(() => {
    const seen = new Set<string>();
    const list: string[] = [];
    [...state.items].reverse().forEach((item) => item.images.forEach((path) => { if (!seen.has(path)) { seen.add(path); list.push(path); } }));
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
      {!files.length && <div className="files-empty"><Decor corner="br" /><p className="pane-note">Файлов пока нет</p></div>}
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

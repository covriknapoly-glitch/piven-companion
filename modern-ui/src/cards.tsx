import { useEffect, useRef, useState, type ReactNode, type WheelEvent } from "react";
import type { DialogueItem, EngineState, WebApi } from "./bridge";
import { Icon } from "./icons";
import { Markdown } from "./markdown";
import { IconButton, Logo, fileName, formatElapsed } from "./ui";

const IMAGE_PATTERN = /\.(png|jpe?g|webp|bmp|gif|tiff?)$/i;
export const ROLE_WIDTH: Record<string, number> = { assistant: 660, user: 480, computer: 480, system: 520, thinking: 660 };

/** Loads a local image through the bridge (the page cannot read files directly). */
export function useImage(api: WebApi, path: string, enabled = true) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let alive = true;
    setSrc("");
    if (enabled && IMAGE_PATTERN.test(path)) void api.image_data(path).then((data) => { if (alive) setSrc(data); });
    return () => { alive = false; };
  }, [api, path, enabled]);
  return src;
}

export function Attachment({ api, path, onView }: { api: WebApi; path: string; onView: (path: string) => void }) {
  const isImage = IMAGE_PATTERN.test(path);
  const src = useImage(api, path, isImage);
  if (isImage) {
    return (
      <button type="button" className={`attachment-image ${src ? "" : "loading"}`} title="Открыть просмотр" onClick={() => onView(path)}>
        {src && <img src={src} alt={fileName(path)} />}
      </button>
    );
  }
  const isDeck = /\.pptx$/i.test(path);
  return (
    <div className="attachment-file">
      <span className="attachment-icon"><Icon name={isDeck ? "presentation" : "file"} size={20} /></span>
      <span className="attachment-copy"><strong>{fileName(path)}</strong><small>{isDeck ? "Презентация PowerPoint" : "Файл"}</small></span>
      <span className="attachment-actions">
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => { void api.open_file(path); }}>Открыть</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { void api.save_copy(path); }}>Сохранить копию</button>
      </span>
    </div>
  );
}

function CardShell({ kind, head, children }: { kind: string; head: ReactNode; children: ReactNode }) {
  return (
    <article className={`card card-${kind}`}>
      <header className="card-head" data-drag-handle title="Потяни, чтобы переместить">{head}</header>
      <div className="card-body">{children}</div>
    </article>
  );
}

export function MessageCard({ api, item, model, canRetry, onCopy, onView, onRetry }:
  { api: WebApi; item: DialogueItem; model: string; canRetry: boolean; onCopy: (text: string) => void; onView: (path: string) => void; onRetry: () => void }) {
  const attachments = item.images.length > 0 && (
    <div className="attachments">{item.images.map((path) => <Attachment key={path} api={api} path={path} onView={onView} />)}</div>
  );
  if (item.role === "system") {
    return (
      <CardShell kind="system" head={<><span className="card-badge"><Icon name="monitor" size={14} /></span><strong>Система</strong></>}>
        <p className="plain small">{item.text}</p>{attachments}
      </CardShell>
    );
  }
  if (item.role === "user" || item.role === "computer") {
    const fromSpeakers = item.role === "computer";
    return (
      <CardShell kind="user" head={<>
        <span className="card-badge user"><Icon name={fromSpeakers ? "volume" : "user"} size={14} /></span>
        <strong>{fromSpeakers ? "Звук компьютера" : "Вы"}</strong>
        <span className="card-spacer" />
        <IconButton icon="copy" label="Копировать" size={15} className="card-action" onClick={() => onCopy(item.text)} />
      </>}>
        {attachments}{item.text && <p className="plain">{item.text}</p>}
      </CardShell>
    );
  }
  return (
    <CardShell kind="assistant" head={<>
      <span className="card-avatar"><Logo size={28} /></span>
      <strong>PIVEN</strong><span className="card-meta">{model}</span>
      <span className="card-spacer" />
      <IconButton icon="copy" label="Копировать ответ" size={15} className="card-action" onClick={() => onCopy(item.text)} />
      <IconButton icon="volume" label="Озвучить" size={15} className="card-action" onClick={() => { void api.speak(item.text); }} />
      {canRetry && <IconButton icon="retry" label="Ответить заново" size={15} className="card-action" onClick={onRetry} />}
    </>}>
      <div className="scrollable">{item.text && <Markdown text={item.text} onCopy={onCopy} />}{attachments}</div>
    </CardShell>
  );
}

export function ThinkingCard({ state, onStop }: { state: EngineState; onStop: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const elapsed = state.busySince ? Math.max(0, Math.floor(now / 1000 - state.busySince)) : 0;
  return (
    <CardShell kind="thinking" head={<>
      <span className="card-avatar"><Logo size={28} pulse /></span>
      <strong>PIVEN</strong><span className="card-meta">{state.settings.model}</span>
      <span className="card-spacer" />
      <button type="button" className="btn btn-ghost btn-sm" onClick={onStop} title="Esc"><Icon name="stop" size={13} /> Остановить</button>
    </>}>
      <div className="thinking-line">
        <span className="thinking-dots" aria-hidden="true"><i /><i /><i /></span>
        <span className="activity">{state.activity || "Думаю"}</span>
        <span className="elapsed">{formatElapsed(elapsed)}</span>
      </div>
      {state.reasoning && (
        <>
          <button type="button" className="link-btn" onClick={() => setExpanded((value) => !value)}>
            <Icon name="chevronRight" size={14} className={expanded ? "rot90" : ""} /> {expanded ? "Скрыть рассуждения" : "Показать рассуждения"}
          </button>
          {expanded && <pre className="reasoning scrollable">{state.reasoning.slice(-4000)}</pre>}
        </>
      )}
    </CardShell>
  );
}

/** Full-screen image viewer: wheel to zoom, drag to move, actions for the file. */
export function Lightbox({ api, path, onClose }: { api: WebApi; path: string; onClose: () => void }) {
  const src = useImage(api, path);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "+" || event.key === "=") setZoom((value) => Math.min(6, value * 1.25));
      if (event.key === "-") setZoom((value) => Math.max(0.2, value / 1.25));
      if (event.key === "0") { setZoom(1); setOffset({ x: 0, y: 0 }); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const onWheel = (event: WheelEvent) => setZoom((value) => Math.min(6, Math.max(0.2, value * Math.exp(-event.deltaY * 0.0015))));
  return (
    <div className="lightbox" onWheel={onWheel}
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="lightbox-bar">
        <span className="lightbox-name">{fileName(path)}</span>
        <span className="lightbox-zoom">{Math.round(zoom * 100)}%</span>
        <IconButton icon="zoomOut" label="Уменьшить (−)" onClick={() => setZoom((value) => Math.max(0.2, value / 1.25))} />
        <IconButton icon="zoomIn" label="Увеличить (+)" onClick={() => setZoom((value) => Math.min(6, value * 1.25))} />
        <IconButton icon="fit" label="Вписать (0)" onClick={() => { setZoom(1); setOffset({ x: 0, y: 0 }); }} />
        <span className="lightbox-sep" />
        <IconButton icon="external" label="Открыть в программе Windows" onClick={() => { void api.open_file(path); }} />
        <IconButton icon="download" label="Сохранить копию" onClick={() => { void api.save_copy(path); }} />
        <IconButton icon="close" label="Закрыть (Esc)" onClick={onClose} />
      </div>
      {src ? (
        <img className="lightbox-image" src={src} alt={fileName(path)} draggable={false}
          style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})` }}
          onMouseDown={(event) => { drag.current = { x: event.clientX, y: event.clientY, ox: offset.x, oy: offset.y }; }}
          onMouseMove={(event) => { const start = drag.current; if (start && event.buttons === 1) setOffset({ x: start.ox + event.clientX - start.x, y: start.oy + event.clientY - start.y }); }}
          onMouseUp={() => { drag.current = null; }} />
      ) : <div className="lightbox-loading">Загружаю…</div>}
    </div>
  );
}

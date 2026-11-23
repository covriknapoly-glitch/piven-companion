import { useEffect, useRef, useState, type ReactNode, type WheelEvent } from "react";
import type { DialogueItem, EngineState, WebApi } from "./bridge";
import { Icon } from "./icons";
import { Markdown } from "./markdown";
import { IconButton, Logo, fileName, formatElapsed } from "./ui";

const IMAGE_PATTERN = /\.(png|jpe?g|webp|bmp|gif|tiff?)$/i;
const mediaCache = new WeakMap<WebApi, Map<string, Promise<string>>>();

function loadMedia(api: WebApi, path: string, thumbnail: boolean) {
  if (!thumbnail) return api.image_data(path).catch(() => "");
  let cache = mediaCache.get(api);
  if (!cache) { cache = new Map(); mediaCache.set(api, cache); }
  const previous = cache.get(path);
  if (previous) {
    cache.delete(path);
    cache.set(path, previous);
    return previous;
  }
  const request = api.image_data(path, true).then(async (src) => {
    if (!src) return "";
    const image = new Image();
    image.src = src;
    await image.decode();
    return src;
  }).catch(() => "");
  cache.set(path, request);
  void request.then((src) => { if (!src && cache.get(path) === request) cache.delete(path); });
  if (cache.size > 12) cache.delete(cache.keys().next().value!);
  return request;
}

export function prefetchChatImages(api: WebApi, items: DialogueItem[]) {
  const paths = [...new Set(items.slice(-16).reverse().flatMap((item) => [...item.images, ...(item.files ?? [])]))];
  return Promise.allSettled(paths.filter((path) => IMAGE_PATTERN.test(path)).slice(0, 6).map((path) => loadMedia(api, path, true)));
}

function useMedia(api: WebApi, path: string, enabled: boolean, thumbnail = false) {
  const [result, setResult] = useState<{ api: WebApi; path: string; src: string } | null>(null);
  useEffect(() => {
    if (!enabled || (!IMAGE_PATTERN.test(path) && !/\.(mp4|webm|mkv)$/i.test(path))) return;
    let alive = true;
    void loadMedia(api, path, thumbnail).then((src) => { if (alive) setResult({ api, path, src }); });
    return () => { alive = false; };
  }, [api, path, enabled, thumbnail]);
  const current = enabled && result?.api === api && result.path === path ? result : null;
  return { src: current?.src ?? "", loading: enabled && !current };
}

export function useImage(api: WebApi, path: string, enabled = true) {
  return useMedia(api, path, enabled).src;
}

function VideoAttachment({ api, path }: { api: WebApi; path: string }) {
  const src = useImage(api, path);
  return (
    <div className="attachment-video">
      {src ? <video src={src} controls loop playsInline /> : <div className="attachment-image loading" />}
      <span className="attachment-actions">
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => { void api.open_file(path); }}>Открыть</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { void api.save_copy(path); }}>Сохранить копию</button>
      </span>
    </div>
  );
}

export function Attachment({ api, path, onView }: { api: WebApi; path: string; onView: (path: string) => void }) {
  const isImage = IMAGE_PATTERN.test(path);
  const { src, loading } = useMedia(api, path, isImage, isImage);
  if (isImage && (src || loading)) {
    return (
      <button type="button" className={`attachment-image ${src ? "" : "loading"}`} title="Открыть просмотр" onClick={() => onView(path)}>
        {src && <img src={src} alt={fileName(path)} />}
      </button>
    );
  }
  if (/\.(mp4|webm|mkv)$/i.test(path)) return <VideoAttachment api={api} path={path} />;
  const isDeck = /\.pptx$/i.test(path);
  const kind = isImage ? "Изображение" : isDeck ? "Презентация PowerPoint" : /\.pdf$/i.test(path) ? "Документ PDF" : /\.docx$/i.test(path) ? "Документ Word" : "Файл";
  return (
    <div className="attachment-file">
      <span className="attachment-icon"><Icon name={isDeck ? "presentation" : "file"} size={20} /></span>
      <span className="attachment-copy"><strong data-i18n-skip>{fileName(path)}</strong><small>{kind}</small></span>
      <span className="attachment-actions">
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => { void api.open_file(path); }}>Открыть</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => { void api.save_copy(path); }}>Сохранить копию</button>
      </span>
    </div>
  );
}

export function Lightbox({ api, path, onClose }: { api: WebApi; path: string; onClose: () => void }) {
  const original = useMedia(api, path, true);
  const preview = useMedia(api, path, IMAGE_PATTERN.test(path), true);
  const src = original.src || preview.src;
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const frame = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (frame.current?.inert) return;
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
    <div className="lightbox" ref={frame} onWheel={onWheel}
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
      ) : <div className="lightbox-loading">{original.loading || preview.loading ? "Загрузка…" : "Не удалось открыть изображение."}</div>}
    </div>
  );
}

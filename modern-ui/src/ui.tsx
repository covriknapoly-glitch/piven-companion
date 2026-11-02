import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { MemoryEstimate, ThinkingOptions, ThinkingValue, WebApi } from "./bridge";
import { Icon, type IconName } from "./icons";
import logoSvg from "./assets/piven_logo.svg";

export const THINKING_NAMES: Record<string, string> = { none: "Без размышления", minimal: "Минимальный", low: "Низкий", medium: "Средний",
  high: "Высокий", xhigh: "Очень высокий", max: "Максимальный", true: "Включено", false: "Выключено" };
export const thinkingName = (value: ThinkingValue | null) => (value === null ? "" : THINKING_NAMES[String(value)] ?? String(value));
/** What the thinking switch can tell about a model that cannot be switched. */
export const thinkingFixed = (options: ThinkingOptions) =>
  options.values.length ? "" : options.default === true ? "Эта модель всегда размышляет." : "Эта модель не размышляет.";

/** A short description of a Hugging Face model from its card (for a conversion, from the original model's card). */
export function ModelDescription({ api, repo, token = "" }: { api: WebApi; repo: string; token?: string }) {
  const [found, setFound] = useState<{ text: string; source: string } | null>(null);
  useEffect(() => {
    let live = true;
    setFound(null);
    if (repo && !repo.startsWith("audiocpp:")) void api.model_description(repo, token).then((reply) => { if (live) setFound(reply); });
    return () => { live = false; };
  }, [api, repo, token]);
  if (!repo || repo.startsWith("audiocpp:")) return null;
  if (!found) return <p className="model-desc muted">Загрузка описания…</p>;
  if (!found.text) return <p className="model-desc muted">У этой модели нет описания на Hugging Face.</p>;
  return (
    <div className="model-desc">
      <p>{found.text}</p>
      {found.source !== repo && <small>Описание исходной модели {found.source}</small>}
    </div>
  );
}

/** A faint grid of dots pressed into a corner of an empty place, fading out towards the middle. */
export function Decor({ corner = "", className = "" }: { corner?: "tl" | "tr" | "bl" | "br" | ""; className?: string }) {
  return <RandomDots className={`${corner ? `decor-corner decor-${corner}` : ""} ${className}`} />;
}

/** A cell's own random number in [0, 1): the same cell always gets the same dot, so resizing only adds or removes dots at the edges. */
function cellRandom(x: number, y: number, salt: number) {
  let h = Math.imul(x, 374761393) ^ Math.imul(y, 668265263) ^ Math.imul(salt, 1274126177);
  h = Math.imul(h ^ (h >>> 13), 1103515245);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

/** Dots on an even grid, each cell randomly empty or holding a dot of random size, with no repeating tile.
 *  Every dot slowly fades in and out on its own rhythm (a 3 to 9 second cycle). Colour from --decor (via the canvas's CSS color). */
export function RandomDots({ step = 20, className = "decor-fill" }: { step?: number; className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    let last = 0;
    const draw = (now: number) => {
      const scale = window.devicePixelRatio || 1;
      const { width, height } = canvas.getBoundingClientRect();
      const pixelWidth = Math.round(width * scale);
      const pixelHeight = Math.round(height * scale);
      if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) { canvas.width = pixelWidth; canvas.height = pixelHeight; }
      const context = canvas.getContext("2d");
      if (!context) return;
      context.setTransform(scale, 0, 0, scale, 0, 0);
      context.clearRect(0, 0, width, height);
      context.fillStyle = getComputedStyle(canvas).color;
      const seconds = now / 1000;
      for (let row = 0; row * step < height + step; row++) {
        for (let column = 0; column * step < width + step; column++) {
          if (cellRandom(column, row, 1) < 0.45) continue;  // leave about half the cells empty
          const size = cellRandom(column, row, 2);
          // the same radii as the corner patterns (1 to 2.2), most dots the smallest
          const radius = size < 0.6 ? 1 : size < 0.72 ? 1.1 : size < 0.82 ? 1.3 : size < 0.9 ? 1.5 : size < 0.96 ? 1.7 : 2.2;
          const period = 3 + cellRandom(column, row, 5) * 6;
          const wave = 0.5 + 0.5 * Math.sin((still ? 0 : seconds) * (Math.PI * 2) / period + cellRandom(column, row, 6) * Math.PI * 2);
          context.globalAlpha = still ? 1 : 0.04 + 0.96 * wave * wave;  // squared: dim most of the time, a clear glow at the peak
          context.beginPath();
          context.arc((column + 0.5) * step, (row + 0.5) * step, radius, 0, Math.PI * 2);
          context.fill();
        }
      }
    };
    // About 20 frames a second is plenty for a slow fade, and nothing is drawn while the window is hidden.
    const tick = (now: number) => {
      frame = requestAnimationFrame(tick);
      if (document.hidden || now - last < 50) return;
      last = now;
      draw(now);
    };
    draw(performance.now());
    if (!still) frame = requestAnimationFrame(tick);
    const redraw = () => draw(performance.now());
    const resize = new ResizeObserver(redraw);
    resize.observe(canvas);
    const theme = new MutationObserver(redraw);  // the dot colour follows the theme
    theme.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => { cancelAnimationFrame(frame); resize.disconnect(); theme.disconnect(); };
  }, [step]);
  return <canvas ref={ref} className={`decor random-dots ${className}`} aria-hidden="true" />;
}
export function Logo({ size = 22, pulse = false }: { size?: number; pulse?: boolean }) {
  // Inline SVG drawn in currentColor, so the logo follows the light and dark theme.
  return <span className={`logo ${pulse ? "pulse" : ""}`} style={{ width: size, height: size }} aria-hidden="true" dangerouslySetInnerHTML={{ __html: logoSvg }} />;
}

export function IconButton({ icon, label, onClick, className = "", disabled = false, size = 18, active = false }:
  { icon: IconName; label: string; onClick?: () => void; className?: string; disabled?: boolean; size?: number; active?: boolean }) {
  return (
    <button className={`icon-btn ${active ? "is-active" : ""} ${className}`} type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled}>
      <Icon name={icon} size={size} />
    </button>
  );
}

export function Button({ children, onClick, kind = "secondary", icon, disabled = false, title, type = "button" }:
  { children: ReactNode; onClick?: () => void; kind?: "primary" | "secondary" | "ghost" | "danger"; icon?: IconName; disabled?: boolean; title?: string; type?: "button" | "submit" }) {
  return (
    <button type={type} className={`btn btn-${kind}`} onClick={onClick} disabled={disabled} title={title}>
      {icon && <Icon name={icon} size={16} />}<span>{children}</span>
    </button>
  );
}

/** Closes a popover or dialog on an outside click or Escape. */
export function useOutsideClose(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => { if (ref.current && !ref.current.contains(event.target as Node)) close(); };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { event.stopPropagation(); close(); } };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open, close]);
  return ref;
}

export interface MenuItem { icon?: IconName; label: string; onClick: () => void; danger?: boolean; disabled?: boolean; hint?: string }

/** A button that opens a small menu of actions. */
export function MenuButton({ icon = "more", label, items, align = "right", className = "" }:
  { icon?: IconName; label: string; items: (MenuItem | "divider")[]; align?: "left" | "right"; className?: string }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useOutsideClose(open, close);
  return (
    <div className={`menu-anchor ${className}`} ref={ref}>
      <IconButton icon={icon} label={label} active={open} onClick={() => setOpen((value) => !value)} />
      {open && (
        <div className={`menu menu-${align}`} role="menu">
          {items.map((item, index) => item === "divider"
            ? <div key={`d${index}`} className="menu-divider" />
            : <button key={item.label} type="button" role="menuitem" disabled={item.disabled} className={item.danger ? "danger" : ""}
                onClick={() => { setOpen(false); item.onClick(); }}>
                {item.icon && <Icon name={item.icon} size={16} />}<span>{item.label}</span>{item.hint && <kbd>{item.hint}</kbd>}
              </button>)}
        </div>
      )}
    </div>
  );
}

export function Modal({ title, subtitle, onClose, children, footer, width = 560, className = "" }:
  { title: string; subtitle?: string; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: number; className?: string }) {
  const ref = useOutsideClose(true, onClose);
  return (
    <div className="modal-backdrop">
      <div className={`modal ${className}`} role="dialog" aria-modal="true" aria-label={title} ref={ref} style={{ width: `min(${width}px, 100%)` }}>
        <header className="modal-head">
          <div><h3>{title}</h3>{subtitle && <p>{subtitle}</p>}</div>
          <IconButton icon="close" label="Закрыть (Esc)" onClick={onClose} />
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}

export function Switch({ checked, onChange, label, disabled = false }: { checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean }) {
  return <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} className={`switch ${checked ? "on" : ""}`} onClick={() => onChange(!checked)}><span /></button>;
}

/** A switch with its text next to it (several options under one heading). */
export function Toggle({ checked, onChange, label, disabled = false }: { checked: boolean; onChange: (value: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <label className={`toggle-row ${disabled ? "disabled" : ""}`}>
      <Switch checked={checked} onChange={onChange} label={label} disabled={disabled} />
      <span>{label}</span>
    </label>
  );
}

export function Field({ label, hint, error, children }: { label: string; hint?: ReactNode; error?: string; children: ReactNode }) {
  return (
    <div className={`field ${error ? "has-error" : ""}`}>
      <div className="field-label"><strong>{label}</strong>{hint && <small>{hint}</small>}</div>
      <div className="field-control">{children}</div>
      {error && <div className="field-error"><Icon name="alert" size={14} />{error}</div>}
    </div>
  );
}

/** Text input that saves on Enter or when focus leaves, and keeps the typed value if it was rejected. */
export function TextSetting({ value, placeholder, onCommit, mono = false, type = "text" }:
  { value: string; placeholder?: string; onCommit: (value: string) => void; mono?: boolean; type?: string }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => { if (draft !== value) onCommit(draft); };
  return <input type={type} className={`input ${mono ? "mono" : ""}`} value={draft} placeholder={placeholder} spellCheck={false}
    onChange={(event) => setDraft(event.target.value)} onBlur={commit} onKeyDown={(event) => { if (event.key === "Enter") commit(); }} />;
}

export const fileName = (path: string) => path.split(/[\\/]/).pop() || path;

export const formatElapsed = (seconds: number) => {
  if (seconds < 60) return `${seconds} с`;
  return `${Math.floor(seconds / 60)} мин ${String(seconds % 60).padStart(2, "0")} с`;
};

// Developer logos (Qwen, Meta, Google, NVIDIA...) by model name, fetched once per name for the whole page.
const logoCache = new Map<string, string>();
const logoWaiters = new Set<() => void>();
let logoQueue: { names: Set<string>; authors: Record<string, string>; archs: Record<string, string> } | null = null;

function requestLogos(api: WebApi, names: string[], authors: Record<string, string>, archs: Record<string, string> = {}) {
  const missing = names.filter((name) => !logoCache.has(name));
  if (!missing.length) return;
  if (!logoQueue) {
    logoQueue = { names: new Set(), authors: {}, archs: {} };
    window.setTimeout(() => {
      const batch = logoQueue!; logoQueue = null;
      const list = [...batch.names];
      list.forEach((name) => logoCache.set(name, ""));
      void api.model_logos(list, batch.authors, batch.archs).then((found) => {
        Object.entries(found || {}).forEach(([name, url]) => logoCache.set(name, url));
        logoWaiters.forEach((wake) => wake());
      });
    }, 30);
  }
  missing.forEach((name) => logoQueue!.names.add(name));
  Object.assign(logoQueue.authors, authors);
  Object.assign(logoQueue.archs, archs);
}

/** Small square developer logo for a model; a neutral box when there is none or it fails to load. */
export function ModelLogo({ api, name, author = "", arch = "", size = 18 }: { api: WebApi | null; name: string; author?: string; arch?: string; size?: number }) {
  const [, redraw] = useState(0);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const wake = () => redraw((value) => value + 1);
    logoWaiters.add(wake);
    if (api && name) requestLogos(api, [name], author ? { [name]: author } : {}, arch ? { [name]: arch } : {});
    return () => { logoWaiters.delete(wake); };
  }, [api, name, author, arch]);
  const url = logoCache.get(name);
  return url && !failed
    ? <img className="model-logo" src={url} width={size} height={size} alt="" draggable={false} onError={() => setFailed(true)} />
    : <span className="model-logo empty" style={{ width: size, height: size }}><Icon name="box" size={Math.round(size * 0.7)} /></span>;
}

export const gigabytes = (bytes: number) => `${(bytes / 2 ** 30).toLocaleString("ru-RU", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} ГБ`;

function memoryDetail(estimate: MemoryEstimate, context: number) {
  const parts = [`веса ${gigabytes(estimate.weights)}`];
  if (estimate.kv) parts.push(`контекст ${Math.round(context / 1024)}K ${gigabytes(estimate.kv)}`);
  parts.push(`прочее ${gigabytes(estimate.other)}`);
  return parts.join(" + ");
}

export const speedText = (estimate: MemoryEstimate) =>
  estimate.speed ? `${estimate.measured ? "" : "≈ "}${Math.round(estimate.speed)} ток/с` : "";
const speedHint = (estimate: MemoryEstimate) => !estimate.speed ? "" : estimate.measured
  ? `Скорость ${Math.round(estimate.speed)} токенов в секунду, измерено на последних ответах.`
  : `Скорость ≈ ${Math.round(estimate.speed)} токенов в секунду, оценка по пропускной способности памяти; после первых ответов покажется измеренная.`;

/** "≈ 6,3 ГБ · ≈ 87 ток/с" next to a model; amber when it will not fit in video memory. */
export function MemoryBadge({ estimate, gpu, context = 0 }: { estimate?: MemoryEstimate | null; gpu: number; context?: number }) {
  if (!estimate) return null;
  const tooBig = gpu > 0 && estimate.total > gpu * 0.95;
  return (
    <span className={`mem-badge ${tooBig ? "warn" : ""}`} title={`При запуске ≈ ${gigabytes(estimate.total)} видеопамяти: ${memoryDetail(estimate, context)}
${speedHint(estimate)}`}>
      ≈ {gigabytes(estimate.total)}{estimate.speed ? <span className={`speed-badge ${estimate.measured ? "measured" : ""}`}>{speedText(estimate)}</span> : null}
    </span>
  );
}

/** A bar of how much of the GPU a set of models takes once loaded. */
export function MemoryBar({ parts, gpu, label, speed }: { parts: { label: string; bytes: number }[]; gpu: number; label: string; speed?: MemoryEstimate }) {
  const total = parts.reduce((sum, part) => sum + part.bytes, 0);
  const scale = Math.max(gpu, total) || 1;
  const tooBig = gpu > 0 && total > gpu * 0.95;
  return (
    <div className={`mem-bar ${tooBig ? "warn" : ""}`}>
      <div className="mem-bar-head"><span>{label}</span><strong>≈ {gigabytes(total)}{gpu ? ` из ${gigabytes(gpu)}` : ""}{speed?.speed ? <span className={`speed-badge ${speed.measured ? "measured" : ""}`} title={speedHint(speed)}>{speedText(speed)}</span> : null}</strong></div>
      <div className="mem-bar-track">{parts.map((part, index) => <i key={part.label} className={`seg${index % 4}`} style={{ width: `${(100 * part.bytes) / scale}%` }} title={`${part.label}: ${gigabytes(part.bytes)}`} />)}</div>
      <div className="mem-bar-legend">{parts.map((part, index) => <span key={part.label}><b className={`seg${index % 4}`} />{part.label} {gigabytes(part.bytes)}</span>)}</div>
    </div>
  );
}

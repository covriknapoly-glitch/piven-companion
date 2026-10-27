import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { MemoryEstimate, WebApi } from "./bridge";
import { Icon, type IconName } from "./icons";
import logoUrl from "./assets/piven_logo.png";

export function Logo({ size = 22, pulse = false }: { size?: number; pulse?: boolean }) {
  return <img className={`logo ${pulse ? "pulse" : ""}`} src={logoUrl} width={size} height={size} alt="" draggable={false} />;
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
let logoQueue: { names: Set<string>; authors: Record<string, string> } | null = null;

function requestLogos(api: WebApi, names: string[], authors: Record<string, string>) {
  const missing = names.filter((name) => !logoCache.has(name));
  if (!missing.length) return;
  if (!logoQueue) {
    logoQueue = { names: new Set(), authors: {} };
    window.setTimeout(() => {
      const batch = logoQueue!; logoQueue = null;
      const list = [...batch.names];
      list.forEach((name) => logoCache.set(name, ""));
      void api.model_logos(list, batch.authors).then((found) => {
        Object.entries(found || {}).forEach(([name, url]) => logoCache.set(name, url));
        logoWaiters.forEach((wake) => wake());
      });
    }, 30);
  }
  missing.forEach((name) => logoQueue!.names.add(name));
  Object.assign(logoQueue.authors, authors);
}

/** Small square developer logo for a model; a neutral box when there is none or it fails to load. */
export function ModelLogo({ api, name, author = "", size = 18 }: { api: WebApi | null; name: string; author?: string; size?: number }) {
  const [, redraw] = useState(0);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const wake = () => redraw((value) => value + 1);
    logoWaiters.add(wake);
    if (api && name) requestLogos(api, [name], author ? { [name]: author } : {});
    return () => { logoWaiters.delete(wake); };
  }, [api, name, author]);
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
    <span className={`mem-badge ${tooBig ? "warn" : ""}`} title={`При запуске ≈ ${gigabytes(estimate.total)} видеопамяти: ${memoryDetail(estimate, context)}${tooBig ? ". Не влезет в видеокарту целиком, часть уйдёт в ОЗУ и будет медленнее." : ""}
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
      {tooBig && <small>Не влезет в видеопамять целиком: часть уйдёт в ОЗУ, и всё будет работать медленнее.</small>}
    </div>
  );
}

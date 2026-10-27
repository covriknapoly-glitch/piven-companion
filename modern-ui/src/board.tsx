import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { Icon } from "./icons";

/**
 * Infinite workspace: cards sit in "world" coordinates inside a panned and
 * zoomed layer. Cards flow top-to-bottom by default; any card can be dragged
 * by its header and keeps that spot (stored per chat in localStorage).
 */

export interface BoardCard {
  key: string;
  role: string;
  width: number;
  node: ReactNode;
}

type Point = { x: number; y: number };
type Offsets = Record<string, Point>;

const GAP = 64;
const MIN_ZOOM = 0.25;
const MAX_ZOOM = 2;
const FOLLOW_BOTTOM_MARGIN = 48; // breathing room under the newest card
const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value));

function readOffsets(chatId: string): Offsets {
  try { return JSON.parse(localStorage.getItem(`piven-board:${chatId}`) || "{}") as Offsets; } catch { return {}; }
}

function writeOffsets(chatId: string, offsets: Offsets) {
  try { localStorage.setItem(`piven-board:${chatId}`, JSON.stringify(offsets)); } catch { /* storage may be unavailable */ }
}

export function Board({ chatId, cards, empty, focus }:
  { chatId: string; cards: BoardCard[]; empty?: ReactNode; focus?: { key: string; nonce: number } | null }) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [pan, setPan] = useState<Point>({ x: 0, y: 40 });
  const [zoom, setZoom] = useState(1);
  const [heights, setHeights] = useState<Record<string, number>>({});
  const [offsets, setOffsets] = useState<Offsets>(() => readOffsets(chatId));
  const [follow, setFollow] = useState(true);
  const [animating, setAnimating] = useState(false);
  const [draggingKey, setDraggingKey] = useState("");
  const drag = useRef<{ mode: "pan" | "card"; key?: string; start: Point; origin: Point; moved: boolean } | null>(null);
  const view = useRef({ pan, zoom });
  view.current = { pan, zoom };


  // ---- layout ----
  const layout = useMemo(() => {
    let cursor = 0;
    return cards.map((card) => {
      const height = heights[card.key] ?? 140;
      const auto = { x: -card.width / 2, y: cursor };
      cursor += height + GAP;
      const position = offsets[card.key] ?? auto;
      return { ...card, height, x: position.x, y: position.y };
    });
  }, [cards, heights, offsets]);

  // ---- measuring ----
  const observer = useRef<ResizeObserver | null>(null);
  const pending = useRef<Record<string, number>>({});
  if (!observer.current && typeof ResizeObserver !== "undefined") {
    observer.current = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const key = (entry.target as HTMLElement).dataset.key;
        if (key) pending.current[key] = Math.round((entry.target as HTMLElement).offsetHeight);
      }
      window.requestAnimationFrame(() => {
        const batch = pending.current;
        pending.current = {};
        setHeights((current) => {
          const changed = Object.entries(batch).some(([key, value]) => current[key] !== value);
          return changed ? { ...current, ...batch } : current;
        });
      });
    });
  }
  useEffect(() => () => observer.current?.disconnect(), []);
  const measure = useCallback((element: HTMLDivElement | null) => {
    if (element) observer.current?.observe(element);
  }, []);

  // ---- camera ----
  const animateTo = useCallback((next: Point, nextZoom?: number) => {
    setAnimating(true);
    setPan(next);
    if (nextZoom !== undefined) setZoom(nextZoom);
    window.setTimeout(() => setAnimating(false), 380);
  }, []);

  const showLatest = useCallback((animate = true) => {
    const viewport = viewportRef.current;
    const last = layout[layout.length - 1];
    if (!viewport || !last) return;
    const { zoom: currentZoom } = view.current;
    const rect = viewport.getBoundingClientRect();
    const centerX = rect.width / 2 - (last.x + last.width / 2) * currentZoom;
    const bottom = (last.y + last.height) * currentZoom;
    const fromTop = 40 - layout[0].y * currentZoom;
    const toBottom = rect.height - FOLLOW_BOTTOM_MARGIN - bottom;
    // Keep the newest card's header on screen when it is taller than the view.
    const headerVisible = 40 - last.y * currentZoom;
    const next = { x: centerX, y: Math.min(fromTop, Math.max(toBottom, headerVisible)) };
    if (animate) animateTo(next); else setPan(next);
  }, [layout, animateTo]);

  const fitAll = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport || !layout.length) return;
    const rect = viewport.getBoundingClientRect();
    const left = Math.min(...layout.map((card) => card.x));
    const right = Math.max(...layout.map((card) => card.x + card.width));
    const top = Math.min(...layout.map((card) => card.y));
    const bottom = Math.max(...layout.map((card) => card.y + card.height));
    const nextZoom = clamp(Math.min((rect.width - 120) / (right - left), (rect.height - FOLLOW_BOTTOM_MARGIN - 60) / (bottom - top)), MIN_ZOOM, 1);
    animateTo({ x: rect.width / 2 - ((left + right) / 2) * nextZoom, y: 40 - top * nextZoom }, nextZoom);
    setFollow(false);
  }, [layout, animateTo]);

  const zoomBy = useCallback((factor: number, anchor?: Point) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const point = anchor ?? { x: rect.width / 2, y: rect.height / 2 };
    const { pan: currentPan, zoom: currentZoom } = view.current;
    const nextZoom = clamp(currentZoom * factor, MIN_ZOOM, MAX_ZOOM);
    const ratio = nextZoom / currentZoom;
    setZoom(nextZoom);
    setPan({ x: point.x - (point.x - currentPan.x) * ratio, y: point.y - (point.y - currentPan.y) * ratio });
    setFollow(false);
  }, []);

  // Follow the conversation: new cards and chat switches bring the latest card into view.
  const lastKey = layout[layout.length - 1]?.key ?? "";
  const lastHeight = layout[layout.length - 1]?.height ?? 0;
  const firstFrame = useRef(true);
  // A chat switch resets the camera before the follow effect below centres the
  // newest card, so it never centres with the previous chat's zoom.
  useLayoutEffect(() => {
    setOffsets(readOffsets(chatId));
    setFollow(true);
    setZoom(1);
    view.current = { ...view.current, zoom: 1 };
    firstFrame.current = true;
  }, [chatId]);
  useLayoutEffect(() => {
    if (!follow || !lastKey) return;
    showLatest(!firstFrame.current);
    firstFrame.current = false;
  }, [follow, lastKey, lastHeight, chatId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Bring a specific card (e.g. a search result) to the centre of the view and highlight it.
  const [flashKey, setFlashKey] = useState("");
  useEffect(() => {
    if (!focus) return;
    const viewport = viewportRef.current;
    const card = layout.find((item) => item.key === focus.key);
    if (!viewport || !card) return;
    const rect = viewport.getBoundingClientRect();
    setFollow(false);
    const tall = card.height > rect.height - 120;
    animateTo({ x: rect.width / 2 - (card.x + card.width / 2), y: tall ? 60 - card.y : rect.height / 2 - (card.y + card.height / 2) }, 1);
    setFlashKey(focus.key);
    const timer = window.setTimeout(() => setFlashKey(""), 1600);
    return () => window.clearTimeout(timer);
  }, [focus?.nonce, layout.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- input ----
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const onWheel = (event: WheelEvent) => {
      const target = event.target as HTMLElement;
      const scrollable = target.closest(".scrollable") as HTMLElement | null;
      if (!event.ctrlKey && scrollable && scrollable.scrollHeight > scrollable.clientHeight) return;
      event.preventDefault();
      const rect = viewport.getBoundingClientRect();
      if (event.ctrlKey) {
        zoomBy(Math.exp(-event.deltaY * 0.0016), { x: event.clientX - rect.left, y: event.clientY - rect.top });
      } else {
        const dx = event.shiftKey ? event.deltaY : event.deltaX;
        const dy = event.shiftKey ? 0 : event.deltaY;
        setPan((current) => ({ x: current.x - dx, y: current.y - dy }));
        setFollow(false);
      }
    };
    viewport.addEventListener("wheel", onWheel, { passive: false });
    return () => viewport.removeEventListener("wheel", onWheel);
  }, [zoomBy]);

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest(".board-hud, .welcome")) return;
    const card = target.closest(".board-card") as HTMLElement | null;
    const handle = target.closest("[data-drag-handle]");
    const start = { x: event.clientX, y: event.clientY };
    if (event.button === 0 && card && handle && !target.closest("button")) {
      const key = card.dataset.key || "";
      const placed = layout.find((item) => item.key === key);
      if (!placed) return;
      drag.current = { mode: "card", key, start, origin: { x: placed.x, y: placed.y }, moved: false };
      setDraggingKey(key);
    } else if (event.button === 1 || (event.button === 0 && !card)) {
      drag.current = { mode: "pan", start, origin: view.current.pan, moved: false };
    } else {
      return;
    }
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state) return;
    const dx = event.clientX - state.start.x;
    const dy = event.clientY - state.start.y;
    if (!state.moved && Math.abs(dx) + Math.abs(dy) < 3) return;
    state.moved = true;
    setFollow(false);
    if (state.mode === "pan") setPan({ x: state.origin.x + dx, y: state.origin.y + dy });
    else if (state.key) {
      const key = state.key;
      const { zoom: currentZoom } = view.current;
      setOffsets((current) => ({ ...current, [key]: { x: state.origin.x + dx / currentZoom, y: state.origin.y + dy / currentZoom } }));
    }
  };

  const onPointerUp = () => {
    const state = drag.current;
    drag.current = null;
    setDraggingKey("");
    if (state?.mode === "card" && state.moved) setOffsets((current) => { writeOffsets(chatId, current); return current; });
  };

  const resetLayout = () => {
    setOffsets({});
    writeOffsets(chatId, {});
    setFollow(true);
  };

  // ---- links between consecutive cards ----
  const links = layout.slice(1).map((card, index) => {
    const from = layout[index];
    const start = { x: from.x + from.width / 2, y: from.y + from.height };
    const end = { x: card.x + card.width / 2, y: card.y };
    const bend = Math.max(28, Math.abs(end.y - start.y) / 2);
    return { key: card.key, d: `M ${start.x} ${start.y} C ${start.x} ${start.y + bend}, ${end.x} ${end.y - bend}, ${end.x} ${end.y - 2}`, end };
  });

  const moved = Object.keys(offsets).length > 0;
  const gridTransform = `translate(${pan.x} ${pan.y}) scale(${zoom})`;
  return (
    <div className={`board ${draggingKey ? "is-dragging" : ""}`} ref={viewportRef}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
      <svg className="board-grid" aria-hidden="true">
        <defs>
          {/* Cutting-mat grid: fine lines every 24 units, a heavier line every fifth. */}
          <pattern id="board-mat" width="120" height="120" patternUnits="userSpaceOnUse" patternTransform={gridTransform}>
            <path className="mat-minor" d="M24 0V120M48 0V120M72 0V120M96 0V120M0 24H120M0 48H120M0 72H120M0 96H120" />
            <path className="mat-major" d="M0.5 0V120M0 0.5H120" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#board-mat)" />
      </svg>
      {/* Pan is a whole-pixel translate; zoom uses CSS `zoom`, which re-lays out and
          re-rasterises text at every scale (transform: scale() stretched a bitmap → blur). */}
      <div className={`board-pan ${animating ? "animating" : ""}`} style={{ transform: `translate(${Math.round(pan.x)}px, ${Math.round(pan.y)}px)` }}>
      <div className="board-world" style={{ zoom }}>
        <svg className="board-links" aria-hidden="true">
          {links.map((link) => (
            <g key={link.key}>
              <path d={link.d} className="board-link" />
              <path d={`M ${link.end.x - 4.5} ${link.end.y - 7} L ${link.end.x} ${link.end.y - 1.5} L ${link.end.x + 4.5} ${link.end.y - 7}`} className="board-arrow" />
            </g>
          ))}
        </svg>
        {layout.map((card) => (
          <div key={card.key} ref={measure} data-key={card.key}
            className={`board-card role-${card.role} ${draggingKey === card.key ? "dragging" : ""} ${flashKey === card.key ? "flash" : ""}`}
            style={{ left: Math.round(card.x), top: Math.round(card.y), width: card.width }}>
            {card.node}
          </div>
        ))}
      </div>
      </div>
      {!cards.length && empty}
      {cards.length > 0 && (
        <div className="board-hud">
          {!follow && <button type="button" className="hud-latest" title="К последнему сообщению" onClick={() => setFollow(true)}><Icon name="arrowDown" size={15} /> К последнему</button>}
          <button type="button" title="Отдалить (Ctrl + колёсико)" onClick={() => zoomBy(1 / 1.2)}><Icon name="zoomOut" size={16} /></button>
          <button type="button" className="hud-zoom" title="Масштаб 100%" onClick={() => { setZoom(1); setFollow(true); }}>{Math.round(zoom * 100)}%</button>
          <button type="button" title="Приблизить (Ctrl + колёсико)" onClick={() => zoomBy(1.2)}><Icon name="zoomIn" size={16} /></button>
          <span className="hud-sep" />
          <button type="button" title="Показать все карточки" onClick={fitAll}><Icon name="fit" size={16} /></button>
          {moved && <button type="button" title="Вернуть карточки на места" onClick={resetLayout}><Icon name="refresh" size={15} /></button>}
        </div>
      )}
    </div>
  );
}

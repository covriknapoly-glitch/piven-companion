import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

export function useSmoothWheel(rootRef: RefObject<HTMLElement | null>, ready: boolean) {
  useEffect(() => {
    const root = rootRef.current;
    if (!ready || !root) return;
    const preference = window.matchMedia(REDUCED_MOTION);
    let scroll: { area: HTMLElement; top: number } | null = null;

    const stop = () => {
      const current = scroll;
      scroll = null;
      if (current?.area.isConnected) current.area.scrollTo({ top: current.area.scrollTop, behavior: "instant" });
    };
    const onWheel = (event: WheelEvent) => {
      if (preference.matches || event.defaultPrevented || !event.cancelable || !(event.target instanceof Element)) return;
      const area = event.target.closest<HTMLElement>("[data-smooth-wheel]");
      if (!area || area.closest("[inert]")) return;
      // Keep trackpad gestures, horizontal scrolling, and wheel-based editing native.
      if (event.ctrlKey || event.shiftKey || event.deltaX !== 0 || event.deltaY === 0 ||
          (event.deltaMode === WheelEvent.DOM_DELTA_PIXEL && Math.abs(event.deltaY) < 24) ||
          event.target.closest("input[type=number], input[type=range], select, textarea")) {
        stop();
        return;
      }
      for (let item: Element | null = event.target; item && item !== area; item = item.parentElement) {
        if (item.scrollHeight > item.clientHeight && /^(auto|scroll)$/.test(getComputedStyle(item).overflowY)) return;
      }

      const limit = area.scrollHeight - area.clientHeight;
      if (limit <= 0) return;
      const delta = event.deltaY * (event.deltaMode === WheelEvent.DOM_DELTA_LINE ? 18 :
        event.deltaMode === WheelEvent.DOM_DELTA_PAGE ? area.clientHeight : 1);
      if (scroll && scroll.area !== area) stop();
      const top = Math.max(0, Math.min(limit, (scroll?.top ?? area.scrollTop) + delta));
      if (!scroll && Math.abs(top - area.scrollTop) < .5) return;
      event.preventDefault();
      scroll = { area, top };
      area.scrollTo({ top, behavior: "smooth" });
    };
    const onScrollEnd = (event: Event) => {
      if (scroll?.area === event.target && Math.abs(scroll.area.scrollTop - scroll.top) < 1) scroll = null;
    };

    root.addEventListener("wheel", onWheel, { passive: false });
    root.addEventListener("scrollend", onScrollEnd, true);
    root.addEventListener("pointerdown", stop, true);
    root.addEventListener("keydown", stop, true);
    preference.addEventListener("change", stop);
    return () => {
      stop();
      root.removeEventListener("wheel", onWheel);
      root.removeEventListener("scrollend", onScrollEnd, true);
      root.removeEventListener("pointerdown", stop, true);
      root.removeEventListener("keydown", stop, true);
      preference.removeEventListener("change", stop);
    };
  }, [rootRef, ready]);
}

export function CodeModeActivation({ enabled }: { enabled: boolean }) {
  const previous = useRef(enabled);
  const [animating, setAnimating] = useState(false);

  useLayoutEffect(() => {
    if (enabled === previous.current) return;
    previous.current = enabled;
    setAnimating(enabled && !window.matchMedia(REDUCED_MOTION).matches);
  }, [enabled]);

  useEffect(() => {
    if (!animating) return;
    const motion = window.matchMedia(REDUCED_MOTION);
    const cancel = () => setAnimating(false);
    motion.addEventListener("change", cancel);
    return () => motion.removeEventListener("change", cancel);
  }, [animating]);

  if (!enabled || !animating) return null;
  return <i className="code-mode-activation" aria-hidden="true" onAnimationEnd={() => setAnimating(false)} />;
}

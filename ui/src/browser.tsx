import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { BrowserState, WebApi } from "./bridge";
import { Icon } from "./icons";
import { IconButton, RandomDots } from "./ui";
import braveIcon from "./assets/sites/brave.png";
import huggingfaceIcon from "./assets/sites/huggingface.png";
import wikipediaIcon from "./assets/sites/wikipedia.png";
import youtubeIcon from "./assets/sites/youtube.png";

const START_LINKS = [
  { title: "Brave Search", url: "https://search.brave.com/", icon: braveIcon },
  { title: "YouTube", url: "https://www.youtube.com/", icon: youtubeIcon },
  { title: "Wikipedia", url: "https://www.wikipedia.org/", icon: wikipediaIcon },
  { title: "Hugging Face", url: "https://huggingface.co/models", icon: huggingfaceIcon },
];

function toUrl(text: string) {
  const clean = text.trim();
  if (!clean) return "";
  if (/^https?:\/\//i.test(clean)) return clean;
  if (/^[\w-]+(\.[\w-]+)+(:\d+)?(\/\S*)?$/.test(clean)) return `https://${clean}`;
  return `https://search.brave.com/search?q=${encodeURIComponent(clean)}`;
}

const NUDGE: Record<string, Keyframe[]> = {
  back: [{ transform: "scaleX(-1) translateX(0)" }, { transform: "scaleX(-1) translateX(4px)", offset: .35 }, { transform: "scaleX(-1) translateX(0)" }],
  forward: [{ transform: "translateX(0)" }, { transform: "translateX(4px)", offset: .35 }, { transform: "translateX(0)" }],
  reload: [{ transform: "rotate(0deg)" }, { transform: "rotate(360deg)" }],
};

const EMPTY: BrowserState = { url: "", title: "", loading: false, canBack: false, canForward: false, notice: "" };

export function BrowserPane({ api, openRequest, covered }:
  { api: WebApi; openRequest: { url: string; nonce: number } | null; covered: boolean }) {
  const [address, setAddress] = useState("");
  const [editing, setEditing] = useState(false);
  const [state, setState] = useState<BrowserState>(EMPTY);

  const [tabs, setTabs] = useState<{ id: number; url: string; title: string }[]>([{ id: 1, url: "", title: "" }]);
  const nextTabId = useRef(2);
  const [activeId, setActiveId] = useState(1);
  const activeTab = tabs.find((tab) => tab.id === activeId) ?? tabs[0];
  const started = Boolean(activeTab.url);
  const viewRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLFormElement>(null);

  const nudge = (selector: string, frames: Keyframe[]) => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    barRef.current?.querySelector(`${selector} .ico`)?.animate(frames, { duration: 240, easing: "cubic-bezier(.16, 1, .3, 1)" });
  };

  const [closing, setClosing] = useState<number[]>([]);
  const tabsRef = useRef<HTMLDivElement>(null);
  const [highlight, setHighlight] = useState<{ left: number; width: number } | null>(null);
  const measure = useCallback(() => {
    const element = tabsRef.current?.querySelector<HTMLElement>(".browser-tab.on");
    if (!element) return;
    const next = { left: element.offsetLeft, width: element.offsetWidth };
    setHighlight((current) => current?.left === next.left && current.width === next.width ? current : next);
  }, []);
  useLayoutEffect(() => {
    measure();
    const element = tabsRef.current;
    if (!element) return;
    const observer = new ResizeObserver(measure);
    element.querySelectorAll(".browser-tab").forEach((tab) => observer.observe(tab));
    return () => observer.disconnect();
  }, [measure, tabs, activeId, closing]);

  useLayoutEffect(() => {
    let current = true;
    for (const id of closing) {
      const tab = tabsRef.current?.querySelector(`[data-tab-id="${id}"]`);
      const fold = tab?.getAnimations().find((animation) =>
        animation instanceof CSSTransition && animation.transitionProperty === "max-width");
      const remove = () => {
        if (!current) return;
        setTabs((list) => list.filter((item) => item.id !== id));
        setClosing((list) => list.filter((item) => item !== id));
      };
      if (fold) void fold.finished.then(remove, remove);
      else remove();
    }
    return () => { current = false; };
  }, [closing]);

  const placement = useRef({ pending: Promise.resolve() as Promise<unknown>, sequence: 0 });
  const placeNative = useCallback((...bounds: Parameters<WebApi["browser_place"]>) => {
    // A slow bridge should apply the latest position before accepting another frame.
    const queue = placement.current;
    const sequence = ++queue.sequence;
    queue.pending = queue.pending.then(() => {
      if (sequence === queue.sequence) return api.browser_place(...bounds);
    }).catch(() => undefined);
  }, [api]);

  useLayoutEffect(() => {
    const element = viewRef.current;
    if (!started || covered || !element) {
      placeNative(0, 0, 0, 0, false);
      return;
    }

    const app = element.closest<HTMLDivElement>(".app");
    let lastBounds = "";
    let frame = 0;
    const place = () => {
      const rect = element.getBoundingClientRect();
      const scale = window.devicePixelRatio || 1;
      const visible = rect.width > 0 && rect.height > 0 && rect.left < window.innerWidth;
      const bounds: Parameters<WebApi["browser_place"]> = visible
        ? [Math.round(rect.left * scale), Math.round(rect.top * scale), Math.round(rect.width * scale), Math.round(rect.height * scale), true]
        : [0, 0, 0, 0, false];
      const key = bounds.join();
      if (key === lastBounds) return;
      lastBounds = key;
      placeNative(...bounds);
    };
    const followSlide = () => {
      place();
      const sliding = app?.getAnimations().some((animation) =>
        animation instanceof CSSTransition && animation.transitionProperty === "--workspace-progress");
      frame = sliding ? requestAnimationFrame(followSlide) : 0;
    };
    const updateSlide = (event: TransitionEvent) => {
      if (event.target !== app || event.propertyName !== "--workspace-progress") return;
      cancelAnimationFrame(frame);
      followSlide();
    };

    const observer = new ResizeObserver(place);
    observer.observe(element);
    window.addEventListener("resize", place);
    const events = ["transitionrun", "transitionend", "transitioncancel"] as const;
    events.forEach((name) => app?.addEventListener(name, updateSlide));
    followSlide();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", place);
      events.forEach((name) => app?.removeEventListener(name, updateSlide));
    };
  }, [placeNative, started, covered]);
  useLayoutEffect(() => () => placeNative(0, 0, 0, 0, false), [placeNative]);

  useEffect(() => {
    const timer = window.setInterval(() => { void api.browser_state().then(setState); }, 400);
    return () => window.clearInterval(timer);
  }, [api]);
  useEffect(() => { if (!editing) setAddress(started ? state.url || activeTab.url : ""); }, [state.url, editing, started]);
  useEffect(() => {
    if (started && state.url && state.url !== "about:blank")
      setTabs((list) => list.map((tab) => (tab.id === activeId ? { ...tab, url: state.url, title: state.title } : tab)));
  }, [state.url, state.title]);
  const switchTab = (id: number) => {
    const tab = tabs.find((item) => item.id === id);
    setActiveId(id);
    if (tab?.url) void api.browser_go(tab.url);
  };
  const newTab = () => {
    const id = nextTabId.current++;
    setTabs((list) => [...list, { id, url: "", title: "" }]);
    setActiveId(id);
  };
  const closeTab = (id: number) => {
    if (closing.includes(id)) return;
    const rest = tabs.filter((tab) => tab.id !== id && !closing.includes(tab.id));
    if (!rest.length) {
      const replacementId = nextTabId.current++;
      setTabs([{ id: replacementId, url: "", title: "" }]);
      setActiveId(replacementId);
      setClosing([]);
      return;
    }

    const position = tabs.filter((tab) => !closing.includes(tab.id)).findIndex((tab) => tab.id === id);
    if (id === activeId) switchTab(rest[Math.min(rest.length - 1, Math.max(0, position - 1))].id);
    setClosing((list) => [...list, id]);
  };

  const [startQuery, setStartQuery] = useState("");
  const go = useCallback((text: string) => {
    const target = toUrl(text);
    if (!target) return;
    setTabs((list) => list.map((tab) => (tab.id === activeId ? { ...tab, url: target } : tab)));
    setAddress(target);
    void api.browser_go(target);
  }, [api, activeId]);
  useEffect(() => { if (openRequest) go(openRequest.url); }, [openRequest]);

  return (
    <div className="browser">
      <div className="browser-tabs" ref={tabsRef}>
        {highlight && <span className="browser-tab-highlight" style={{ transform: `translateX(${highlight.left}px)`, width: highlight.width }} />}
        {tabs.map((tab) => (
          <div key={tab.id} data-tab-id={tab.id} inert={closing.includes(tab.id)}
            className={`browser-tab ${tab.id === activeId ? "on" : ""} ${closing.includes(tab.id) ? "closing" : ""}`}>
            <button type="button" onClick={() => switchTab(tab.id)} title={tab.url || "Новая вкладка"}>{tab.title || (tab.url ? tab.url.replace(/^https?:\/\/(www\.)?/, "") : "Новая вкладка")}</button>
            <IconButton icon="close" label="Закрыть вкладку" size={12} onClick={() => closeTab(tab.id)} />
          </div>
        ))}
        <IconButton icon="plus" label="Новая вкладка" size={14} onClick={newTab} />
      </div>
      <form className="browser-bar" ref={barRef} onSubmit={(event) => { event.preventDefault(); go(address); (document.activeElement as HTMLElement | null)?.blur(); }}>
        <IconButton icon="arrowRight" className="flip-x nav-back" label="Назад" size={15} disabled={!state.canBack}
          onClick={() => { nudge(".nav-back", NUDGE.back); void api.browser_command("back"); }} />
        <IconButton icon="arrowRight" className="nav-forward" label="Вперёд" size={15} disabled={!state.canForward}
          onClick={() => { nudge(".nav-forward", NUDGE.forward); void api.browser_command("forward"); }} />

        <IconButton key={state.loading ? "stop" : "reload"} icon={state.loading ? "close" : "refresh"} className="nav-reload"
          label={state.loading ? "Остановить" : "Обновить"} size={15} disabled={!started}
          onClick={() => { if (!state.loading) nudge(".nav-reload", NUDGE.reload); void api.browser_command(state.loading ? "stop" : "reload"); }} />
        <input className="browser-address" value={address} spellCheck={false} placeholder="адрес или поиск"
          onChange={(event) => setAddress(event.target.value)}
          onFocus={(event) => { setEditing(true); event.currentTarget.select(); }} onBlur={() => setEditing(false)} />
        <IconButton icon="external" label="Открыть в обычном браузере" size={15} disabled={!state.url} onClick={() => { void api.open_url(state.url); }} />
      </form>
      {state.loading && <div className="browser-progress"><i /></div>}
      {state.notice && <div className="browser-notice">{state.notice}</div>}
      <div className="browser-view" ref={viewRef}>
        {!started && (
          <div className="browser-start">
            <form className="start-search" onSubmit={(event) => { event.preventDefault(); go(startQuery); }}>
              <Icon name="search" size={16} />
              <input value={startQuery} spellCheck={false} placeholder="Поиск или адрес" onChange={(event) => setStartQuery(event.target.value)} />
            </form>
            <div className="start-tiles">
              {START_LINKS.map((link) => (
                <button key={link.url} type="button" className="start-tile" title={link.url.replace(/^https:\/\/(www\.)?/, "")} onClick={() => go(link.url)}>
                  <span className="start-icon"><img src={link.icon} alt="" width={26} height={26} draggable={false} /></span><span className="start-name">{link.title}</span>
                </button>
              ))}
            </div>
            <RandomDots />
          </div>
        )}
        {started && covered && <div className="browser-note">Браузер скрыт, пока открыто окно поверх.</div>}
      </div>
    </div>
  );
}

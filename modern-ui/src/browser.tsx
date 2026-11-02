import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { BrowserState, WebApi } from "./bridge";
import { IconButton, RandomDots } from "./ui";

const START_LINKS = [
  { title: "Brave Search", url: "https://search.brave.com/" },
  { title: "YouTube", url: "https://www.youtube.com/" },
  { title: "Википедия", url: "https://ru.wikipedia.org/" },
  { title: "Hugging Face", url: "https://huggingface.co/models" },
];

/** Address bar text → a URL: keeps addresses, turns everything else into a search. */
function toUrl(text: string) {
  const clean = text.trim();
  if (!clean) return "";
  if (/^https?:\/\//i.test(clean)) return clean;
  if (/^[\w-]+(\.[\w-]+)+(:\d+)?(\/\S*)?$/.test(clean)) return `https://${clean}`;
  return `https://search.brave.com/search?q=${encodeURIComponent(clean)}`;
}

const TAB_FOLD_MS = 200;   // matches the .browser-tab.closing transition

// Icon motions on a click, as in Chrome: the arrows step their way, reload turns once. The back arrow is the
// forward one mirrored (scaleX(-1)), so its steps keep the mirror and move "forward" in mirrored space.
const NUDGE: Record<string, Keyframe[]> = {
  back: [{ transform: "scaleX(-1) translateX(0)" }, { transform: "scaleX(-1) translateX(4px)", offset: .35 }, { transform: "scaleX(-1) translateX(0)" }],
  forward: [{ transform: "translateX(0)" }, { transform: "translateX(4px)", offset: .35 }, { transform: "translateX(0)" }],
  reload: [{ transform: "rotate(0deg)" }, { transform: "rotate(360deg)" }],
};

const EMPTY: BrowserState = { url: "", title: "", loading: false, canBack: false, canForward: false, notice: "" };

/**
 * The right-hand browser. The page only draws the toolbar and an empty box; a separate native
 * WebView2 (native_browser.py) is laid over that box. Native controls sit above the page, so the
 * box is hidden while a dialog or the image viewer is open (`covered`).
 */
export function BrowserPane({ api, openRequest, covered }:
  { api: WebApi; openRequest: { url: string; nonce: number } | null; covered: boolean }) {
  const [address, setAddress] = useState("");
  const [editing, setEditing] = useState(false);
  const [state, setState] = useState<BrowserState>(EMPTY);
  // Page tabs share one native browser: switching a tab loads its page again.
  const [tabs, setTabs] = useState<{ id: number; url: string; title: string }[]>([{ id: 1, url: "", title: "" }]);
  const [activeId, setActiveId] = useState(1);
  const activeTab = tabs.find((tab) => tab.id === activeId) ?? tabs[0];
  const started = Boolean(activeTab.url);
  const viewRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLFormElement>(null);
  /** Play one of the NUDGE motions on a toolbar button's icon (again on every click). */
  const nudge = (selector: string, frames: Keyframe[]) => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    barRef.current?.querySelector(`${selector} .ico`)?.animate(frames, { duration: 420, easing: "cubic-bezier(.16, 1, .3, 1)" });
  };
  // A closed tab first folds up (TAB_FOLD_MS), then leaves the list; the highlight slides to the active tab.
  const [closing, setClosing] = useState<number[]>([]);
  const tabsRef = useRef<HTMLDivElement>(null);
  const [highlight, setHighlight] = useState<{ left: number; width: number } | null>(null);
  const measure = useCallback(() => {
    const element = tabsRef.current?.querySelector<HTMLElement>(".browser-tab.on");
    if (element) setHighlight({ left: element.offsetLeft, width: element.offsetWidth });
  }, []);
  useLayoutEffect(() => {
    measure();
    const element = tabsRef.current;
    if (!element) return;
    const observer = new ResizeObserver(measure);   // follows tabs that grow in or fold up next to the active one
    element.querySelectorAll(".browser-tab").forEach((tab) => observer.observe(tab));
    return () => observer.disconnect();
  }, [measure, tabs, activeId, closing]);

  const place = useCallback(() => {
    const element = viewRef.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    const scale = window.devicePixelRatio || 1;
    void api.browser_place(Math.round(rect.left * scale), Math.round(rect.top * scale), Math.round(rect.width * scale), Math.round(rect.height * scale), started && !covered);
  }, [api, started, covered]);

  useLayoutEffect(() => {
    place();
    const element = viewRef.current;
    const observer = new ResizeObserver(() => place());
    if (element) observer.observe(element);
    window.addEventListener("resize", place);
    // The panel slides in without changing size, so follow it once the slide ends.
    const slid = (event: AnimationEvent) => { if ((event.target as Element).classList?.contains("workspace")) place(); };
    document.addEventListener("animationend", slid);
    return () => { observer.disconnect(); window.removeEventListener("resize", place); document.removeEventListener("animationend", slid); };
  }, [place]);
  useEffect(() => () => { void api.browser_place(0, 0, 0, 0, false); }, [api]);

  useEffect(() => {
    const timer = window.setInterval(() => { void api.browser_state().then(setState); }, 400);
    return () => window.clearInterval(timer);
  }, [api]);
  useEffect(() => { if (!editing) setAddress(started ? state.url || activeTab.url : ""); }, [state.url, editing, started]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // the open page and its title belong to the active tab
    if (started && state.url && state.url !== "about:blank")
      setTabs((list) => list.map((tab) => (tab.id === activeId ? { ...tab, url: state.url, title: state.title } : tab)));
  }, [state.url, state.title]); // eslint-disable-line react-hooks/exhaustive-deps
  const switchTab = (id: number) => {
    const tab = tabs.find((item) => item.id === id);
    setActiveId(id);
    if (tab?.url) void api.browser_go(tab.url);
  };
  const newTab = () => {
    const id = Math.max(...tabs.map((tab) => tab.id)) + 1;
    setTabs((list) => [...list, { id, url: "", title: "" }]);
    setActiveId(id);
  };
  const closeTab = (id: number) => {
    if (closing.includes(id)) return;
    const rest = tabs.filter((tab) => tab.id !== id && !closing.includes(tab.id));
    if (!rest.length) {   // the last tab is replaced by a new empty one at once
      setTabs([{ id: id + 1, url: "", title: "" }]); setActiveId(id + 1); return;
    }
    // the tab to the left of the closed one becomes active (or the first, when the closed one was first)
    const position = tabs.filter((tab) => !closing.includes(tab.id)).findIndex((tab) => tab.id === id);
    if (id === activeId) switchTab(rest[Math.min(rest.length - 1, Math.max(0, position - 1))].id);
    setClosing((list) => [...list, id]);
    window.setTimeout(() => {
      setTabs((list) => list.filter((tab) => tab.id !== id));
      setClosing((list) => list.filter((item) => item !== id));
    }, TAB_FOLD_MS);
  };

  const go = useCallback((text: string) => {
    const target = toUrl(text);
    if (!target) return;
    setTabs((list) => list.map((tab) => (tab.id === activeId ? { ...tab, url: target } : tab)));
    setAddress(target);
    void api.browser_go(target);
  }, [api, activeId]);
  useEffect(() => { if (openRequest) go(openRequest.url); }, [openRequest]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="browser">
      <div className="browser-tabs" ref={tabsRef}>
        {highlight && <span className="browser-tab-highlight" style={{ transform: `translateX(${highlight.left}px)`, width: highlight.width }} />}
        {tabs.map((tab) => (
          <div key={tab.id} className={`browser-tab ${tab.id === activeId ? "on" : ""} ${closing.includes(tab.id) ? "closing" : ""}`}>
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
        {/* keyed by the mode, so the icon swaps with its own little turn when loading starts or ends */}
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
            {START_LINKS.map((link) => (
              <button key={link.url} type="button" onClick={() => go(link.url)}><span>{link.title}</span>{link.url.replace(/^https:\/\/(www\.)?/, "")}</button>
            ))}
            <RandomDots />
          </div>
        )}
        {started && covered && <div className="browser-note">Браузер скрыт, пока открыто окно поверх.</div>}
      </div>
    </div>
  );
}

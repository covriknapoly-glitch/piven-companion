import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { BrowserState, WebApi } from "./bridge";
import { IconButton } from "./ui";

const START_LINKS = [
  { title: "Поиск Google", url: "https://www.google.com/" },
  { title: "YouTube", url: "https://www.youtube.com/" },
  { title: "Википедия", url: "https://ru.wikipedia.org/" },
  { title: "Minecraft Wiki", url: "https://minecraft.wiki/" },
  { title: "Модели Ollama", url: "https://ollama.com/library" },
];

/** Address bar text → a URL: keeps addresses, turns everything else into a search. */
function toUrl(text: string) {
  const clean = text.trim();
  if (!clean) return "";
  if (/^https?:\/\//i.test(clean)) return clean;
  if (/^[\w-]+(\.[\w-]+)+(:\d+)?(\/\S*)?$/.test(clean)) return `https://${clean}`;
  return `https://www.google.com/search?q=${encodeURIComponent(clean)}`;
}

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
    return () => { observer.disconnect(); window.removeEventListener("resize", place); };
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
    const rest = tabs.filter((tab) => tab.id !== id);
    if (!rest.length) { setTabs([{ id: id + 1, url: "", title: "" }]); setActiveId(id + 1); return; }
    setTabs(rest);
    if (id === activeId) switchTab(rest[Math.max(0, tabs.findIndex((tab) => tab.id === id) - 1)].id);
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
      <div className="browser-tabs">
        {tabs.map((tab) => (
          <div key={tab.id} className={`browser-tab ${tab.id === activeId ? "on" : ""}`}>
            <button type="button" onClick={() => switchTab(tab.id)} title={tab.url || "Новая вкладка"}>{tab.title || (tab.url ? tab.url.replace(/^https?:\/\/(www\.)?/, "") : "Новая вкладка")}</button>
            <IconButton icon="close" label="Закрыть вкладку" size={12} onClick={() => closeTab(tab.id)} />
          </div>
        ))}
        <IconButton icon="plus" label="Новая вкладка" size={14} onClick={newTab} />
      </div>
      <form className="browser-bar" onSubmit={(event) => { event.preventDefault(); go(address); (document.activeElement as HTMLElement | null)?.blur(); }}>
        <IconButton icon="arrowRight" className="flip-x" label="Назад" size={15} disabled={!state.canBack} onClick={() => { void api.browser_command("back"); }} />
        <IconButton icon="arrowRight" label="Вперёд" size={15} disabled={!state.canForward} onClick={() => { void api.browser_command("forward"); }} />
        <IconButton icon={state.loading ? "close" : "refresh"} label={state.loading ? "Остановить" : "Обновить"} size={15} disabled={!started}
          onClick={() => { void api.browser_command(state.loading ? "stop" : "reload"); }} />
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
            <p>Введи адрес или запрос сверху. Ссылки из ответов компаньона тоже открываются здесь.</p>
            {START_LINKS.map((link) => (
              <button key={link.url} type="button" onClick={() => go(link.url)}><span>{link.title}</span>{link.url.replace(/^https:\/\/(www\.)?/, "")}</button>
            ))}
          </div>
        )}
        {started && covered && <div className="browser-note">Браузер скрыт, пока открыто окно поверх.</div>}
      </div>
    </div>
  );
}

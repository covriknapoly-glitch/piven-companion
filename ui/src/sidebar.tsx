import { useEffect, useMemo, useState, type ReactNode, type RefObject } from "react";
import type { ChatSummary, EngineState, SearchHit, WebApi } from "./bridge";
import { Icon } from "./icons";
import { Decor, IconButton, Logo, MenuButton } from "./ui";

export interface ChatActions {
  select: (chat: ChatSummary) => void;
  rename: (chat: ChatSummary, title: string) => void;
  pin: (chat: ChatSummary) => void;
  fork: (chat: ChatSummary) => void;
  exportChat: (chat: ChatSummary, markdown: boolean) => void;
  remove: (chat: ChatSummary) => void;
  moveToProjects: (chat: ChatSummary) => void;
  project: (chat: ChatSummary, action: "folder" | "open") => void;
}

const folderName = (path: string) => path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? path;

function ChatRow({ chat, active, canFork, actions, branches }:
  { chat: ChatSummary; active: boolean; canFork: boolean; actions: ChatActions; branches?: { open: boolean; onToggle: () => void } }) {
  const folder = chat.code && chat.root ? folderName(chat.root) : "";
  const shownTitle = chat.code && chat.title === "Новый чат" ? folder || "Новый проект" : chat.title;
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(chat.title);
  const commit = () => {
    setRenaming(false);
    const clean = title.trim();
    if (clean && clean !== chat.title) actions.rename(chat, clean); else setTitle(chat.title);
  };
  if (renaming) {
    return (
      <div className="chat-row renaming">
        <input autoFocus value={title} maxLength={80} onChange={(event) => setTitle(event.target.value)} onBlur={commit}
          onKeyDown={(event) => { if (event.key === "Enter") commit(); if (event.key === "Escape") { setTitle(chat.title); setRenaming(false); } }} />
      </div>
    );
  }
  return (
    <div className={`chat-row ${active ? "active" : ""}`}>
      {branches && <button type="button" className="icon-btn chat-branch-toggle" aria-expanded={branches.open}
        aria-label={branches.open ? "Свернуть ветки" : "Раскрыть ветки"} title={branches.open ? "Свернуть ветки" : "Раскрыть ветки"} onClick={branches.onToggle}>
        <Icon name={branches.open ? "chevronDown" : "chevronRight"} size={14} />
      </button>}
      <button type="button" className="chat-row-main" aria-current={active ? "page" : undefined}
        onClick={() => actions.select(chat)} onDoubleClick={() => { setTitle(chat.title); setRenaming(true); }} title={chat.root || chat.title}>
        <span className="chat-row-title">{chat.pinned && <Icon name="pin" size={12} className="pin-mark" />}
          {chat.branchOf && <Icon name="branch" size={13} className="pin-mark" />}{shownTitle}
          {chat.busy && <span className="chat-busy" title="Пишет ответ"><i /><i /><i /></span>}
          {!chat.busy && chat.unread && <span className="chat-unread" title="Новый ответ" />}</span>
        {!folder && <span className="chat-row-preview">{chat.preview || "Пока без сообщений"}</span>}
      </button>
      <MenuButton label={chat.code ? "Действия с проектом" : "Действия с чатом"} className="chat-row-menu" items={[
        { icon: "edit" as const, label: "Переименовать", onClick: () => { setTitle(chat.title); setRenaming(true); } },
        { icon: "pin", label: chat.pinned ? "Открепить" : "Закрепить", onClick: () => actions.pin(chat) },
        { icon: "branch", label: "Создать ветку", disabled: !canFork, onClick: () => actions.fork(chat) },
        { icon: "code", label: chat.code ? "Сделать обычным чатом" : "Сделать проектом", onClick: () => actions.moveToProjects(chat) },
        ...(chat.code ? [{ icon: "folder" as const, label: folder ? "Сменить папку…" : "Выбрать папку…", onClick: () => actions.project(chat, "folder") }] : []),
        ...(folder ? [
          { icon: "external" as const, label: "Открыть в проводнике", onClick: () => actions.project(chat, "open") },
        ] : []),
        "divider",
        { icon: "share", label: "Экспорт в Markdown", onClick: () => actions.exportChat(chat, true) },
        { icon: "file", label: "Экспорт в текст", onClick: () => actions.exportChat(chat, false) },
        "divider",
        { icon: "trash", label: "Удалить…", danger: true, disabled: Boolean(chat.busy), onClick: () => actions.remove(chat) },
      ]} />
    </div>
  );
}

const recentlyUpdated = (a: ChatSummary, b: ChatSummary) => (b.updated || 0) - (a.updated || 0);

function branchHierarchy(chats: ChatSummary[]) {
  const ids = new Set(chats.map((chat) => chat.id));
  const parents = new Map<string, string>();
  for (const chat of chats) {
    const parent = chat.branchOf;
    if (!parent || !ids.has(parent)) continue;
    // An imported cycle must not hide any of its chats from the sidebar.
    let ancestor: string | undefined = parent;
    while (ancestor && ancestor !== chat.id) ancestor = parents.get(ancestor);
    if (ancestor !== chat.id) parents.set(chat.id, parent);
  }
  const children = new Map<string, ChatSummary[]>();
  const latest = new Map<string, number>();
  for (const chat of [...chats].sort(recentlyUpdated)) {
    const parent = parents.get(chat.id);
    if (parent) {
      const siblings = children.get(parent) ?? [];
      siblings.push(chat);
      children.set(parent, siblings);
    }
    // The first activity seen for each parent is the most recent in its subtree.
    let current: string | undefined = chat.id;
    while (current && !latest.has(current)) {
      latest.set(current, chat.updated || 0);
      current = parents.get(current);
    }
  }
  return { parents, children, latest };
}

function dateGroups(chats: ChatSummary[], latest: (chat: ChatSummary) => number): [string, ChatSummary[]][] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const day = 86_400_000;
  const bounds: [string, number][] = [["Сегодня", today.getTime()], ["Вчера", today.getTime() - day], ["За неделю", today.getTime() - 6 * day], ["Раньше", -Infinity]];
  const groups = new Map<string, ChatSummary[]>();
  for (const chat of [...chats].sort((a, b) => latest(b) - latest(a))) {
    const time = latest(chat) * 1000;
    const caption = bounds.find(([, from]) => time >= from)![0];
    groups.set(caption, [...(groups.get(caption) ?? []), chat]);
  }
  return bounds.map(([caption]) => [caption, groups.get(caption) ?? []] as [string, ChatSummary[]]).filter(([, list]) => list.length > 0);
}

export function Sidebar({ api, state, actions, searchRef, onNewChat, onOpenHit, searchPreset, onSettings, open, onToggle }:
  { api: WebApi; state: EngineState; actions: ChatActions; searchRef: RefObject<HTMLInputElement | null>; onNewChat: () => void;
    open: boolean; onToggle: () => void;
    onOpenHit: (hit: SearchHit) => void; searchPreset?: { text: string; nonce: number } | null; onSettings: () => void }) {
  const [query, setQuery] = useState("");
  useEffect(() => { if (searchPreset) setQuery(searchPreset.text); }, [searchPreset]);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [hidden, setHidden] = useState<string[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const projects = state.code.on;
  const needle = query.trim().toLowerCase();
  const kind = useMemo(() => state.chats.filter((chat) => Boolean(chat.code) === projects), [state.chats, projects]);
  const filtered = useMemo(() => {
    return needle ? kind.filter((chat) => chat.title.toLowerCase().includes(needle) || chat.preview.toLowerCase().includes(needle) || (chat.root ?? "").toLowerCase().includes(needle)) : kind;
  }, [kind, needle]);
  const { parents, children, latest } = useMemo(() => branchHierarchy(kind), [kind]);
  const activeAncestors: string[] = [];
  for (let parent = parents.get(state.activeChatId); parent; parent = parents.get(parent)) activeAncestors.push(parent);
  const activePath = JSON.stringify(activeAncestors);
  useEffect(() => {
    const ancestors: string[] = JSON.parse(activePath);
    if (ancestors.length) setExpanded((open) => new Set([...open, ...ancestors]));
  }, [state.activeChatId, activePath]);
  // One search box: chat titles above, matching messages from these chats below.
  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) { setHits([]); return; }
    let live = true;
    const timer = window.setTimeout(() => { void api.search_messages(text).then((found) => { if (live) setHits(found); }); }, 200);
    return () => { live = false; window.clearTimeout(timer); };
  }, [api, query]);
  const kindIds = useMemo(() => new Set(kind.map((chat) => chat.id)), [kind]);
  const messageHits = hits.filter((hit) => kindIds.has(hit.chatId)).slice(0, 12);
  const doneKey = (row: EngineState["downloads"][number]) => `${row.kind}:${row.title}:${row.state}`;
  const downloads = state.downloads.filter((row) => row.state === "running" || !hidden.includes(doneKey(row)));
  const pinned = filtered.filter((chat) => chat.pinned);
  const groups = useMemo((): [string, ChatSummary[]][] => {
    const rest = filtered.filter((chat) => !chat.pinned && (needle || !parents.has(chat.id)));
    const activity = (chat: ChatSummary) => (needle ? chat.updated : latest.get(chat.id)) || 0;
    if (!projects) return dateGroups(rest, activity);
    return rest.length ? [["Проекты", rest.sort((a, b) => activity(b) - activity(a))]] : [];
  }, [filtered, projects, needle, parents, latest]);
  const toggleBranches = (id: string) => setExpanded((open) => {
    const next = new Set(open);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
  const renderChat = (chat: ChatSummary, depth = 0, shortcut = false): ReactNode => {
    const branches = shortcut || needle ? undefined : children.get(chat.id);
    const open = expanded.has(chat.id);
    return <div key={chat.id}>
      <ChatRow key={`${chat.title}-${chat.pinned}`} chat={chat} active={chat.id === state.activeChatId}
        canFork={chat.count > 0 && !chat.busy && !state.listening.running} actions={actions}
        branches={branches && { open, onToggle: () => toggleBranches(chat.id) }} />
      {branches && open && <div className={depth < 3 ? "chat-branches" : undefined}>
        {branches.map((branch) => renderChat(branch, depth + 1))}
      </div>}
    </div>;
  };
  const toggleLabel = open ? "Скрыть панель (Ctrl+B)" : "Показать панель (Ctrl+B)";
  const content = (
    <div id="chat-sidebar-content" className="sidebar-content" inert={!open}>
      <div className="nav-decor"><Decor corner="bl" /></div>
      <div className="brand">
        <Logo size={29} />
        <div className="brand-copy"><strong>PIVEN</strong></div>
      </div>

      <button type="button" className="new-chat" onClick={onNewChat} title="Ctrl+N">
        <Icon name="compose" size={17} /><span>{projects ? "Новый проект" : "Новый чат"}</span>
      </button>

      <div className="side-search">
        <label className="search-field"><Icon name="search" size={15} />
          <input ref={searchRef} placeholder="Поиск" title={projects ? "Ищет по названиям проектов и по сообщениям в них" : "Ищет по названиям чатов и по сообщениям в них"}
            value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") setQuery(""); }} />
          {query && <button type="button" aria-label="Очистить" onClick={() => setQuery("")}><Icon name="close" size={13} /></button>}
        </label>
      </div>

      <nav className="chat-nav" data-smooth-wheel>
        {pinned.length > 0 && <><div className="nav-caption">Закреплённые</div>{pinned.map((chat) => renderChat(chat, 0, parents.has(chat.id)))}</>}
        {groups.map(([caption, chats]) => <div key={caption} className="nav-group"><div className="nav-caption">{caption}</div>{chats.map((chat) => renderChat(chat))}</div>)}
        {!filtered.length && !messageHits.length && <div className="nav-empty">{query.trim() ? "Ничего не найдено" : projects ? "Проектов пока нет" : "Чатов пока нет"}</div>}
        {messageHits.length > 0 && (
          <div className="nav-group">
            <div className="nav-caption">В сообщениях</div>
            {messageHits.map((hit) => (
              <button key={`${hit.chatId}-${hit.index}`} type="button" className="nav-hit" onClick={() => onOpenHit(hit)}>
                <strong>{hit.chatTitle}</strong><span>{hit.excerpt}</span>
              </button>
            ))}
          </div>
        )}
      </nav>

      {downloads.length > 0 && (
        <div className="side-downloads" aria-label="Загрузки">
          {downloads.map((row) => (
            <div key={row.kind} className={`side-download ${row.state}`}>
              <div className="side-download-head">
                <Icon name={row.state === "error" ? "alert" : row.state === "done" ? "check" : "download"} size={14} />
                <span className="side-download-title" title={row.title}>{row.title || (row.kind === "model" ? "Модель" : "Голосовая модель")}</span>
                <span className="side-download-pct">{row.state === "running" ? `${row.percent}%` : row.state === "done" ? "готово" : row.state === "cancelled" ? "отменено" : "ошибка"}</span>
                {row.state === "running"
                  ? <IconButton icon="close" label="Отменить загрузку" size={13} onClick={() => { void (row.kind === "model" ? api.hf_cancel() : api.voice_cancel()); }} />
                  : <IconButton icon="close" label="Убрать" size={13} onClick={() => setHidden((list) => [...list, doneKey(row)])} />}
              </div>
              <div className="progress-track"><i style={{ width: `${row.percent}%` }} /></div>
              {row.message && <small title={row.message}>{row.message}</small>}
            </div>
          ))}
        </div>
      )}

      <div className="side-foot">
        <IconButton icon="settings" label="Настройки (Ctrl+,)" onClick={onSettings} />
      </div>
    </div>
  );
  return (
    <aside id="chat-sidebar" className="sidebar" aria-label={projects ? "Проекты" : "Чаты"}>
      <button type="button" className="icon-btn sidebar-toggle" aria-expanded={open} aria-controls="chat-sidebar-content"
        aria-label={toggleLabel} title={toggleLabel} onClick={onToggle}>
        <Icon name={open ? "sidebar" : "sidebarOpen"} size={18} />
      </button>
      {content}
    </aside>
  );
}

import { useMemo, useState, type RefObject } from "react";
import type { ChatSummary, EngineState, WebApi } from "./bridge";
import { Icon } from "./icons";
import { Decor, IconButton, Logo, MenuButton } from "./ui";

export interface ChatActions {
  select: (chat: ChatSummary) => void;
  rename: (chat: ChatSummary, title: string) => void;
  pin: (chat: ChatSummary) => void;
  exportChat: (chat: ChatSummary, markdown: boolean) => void;
  remove: (chat: ChatSummary) => void;
  moveToProjects: (chat: ChatSummary) => void;
  project: (chat: ChatSummary, action: "folder" | "open") => void;
}

const folderName = (path: string) => path.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? path;

function ChatRow({ chat, active, disabled, actions }: { chat: ChatSummary; active: boolean; disabled: boolean; actions: ChatActions }) {
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
      <button type="button" className="chat-row-main" disabled={disabled} onClick={() => actions.select(chat)} onDoubleClick={() => { setTitle(chat.title); setRenaming(true); }} title={chat.root || chat.title}>
        <span className="chat-row-title">{chat.pinned && <Icon name="pin" size={12} className="pin-mark" />}{shownTitle}
          {chat.busy && <span className="chat-busy" title="Пишет ответ"><i /><i /><i /></span>}
          {!chat.busy && chat.unread && <span className="chat-unread" title="Новый ответ" />}</span>
        {folder ? <span className="chat-row-folder" data-i18n-skip>{folder}</span> : <span className="chat-row-preview">{chat.preview || "Пока без сообщений"}</span>}
      </button>
      <MenuButton label={chat.code ? "Действия с проектом" : "Действия с чатом"} className="chat-row-menu" items={[
        { icon: "edit" as const, label: "Переименовать", onClick: () => { setTitle(chat.title); setRenaming(true); } },
        { icon: "pin", label: chat.pinned ? "Открепить" : "Закрепить", onClick: () => actions.pin(chat) },
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

function dateGroups(chats: ChatSummary[]): [string, ChatSummary[]][] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const day = 86_400_000;
  const bounds: [string, number][] = [["Сегодня", today.getTime()], ["Вчера", today.getTime() - day], ["За неделю", today.getTime() - 6 * day], ["Раньше", -Infinity]];
  const groups = new Map<string, ChatSummary[]>();
  for (const chat of [...chats].sort((a, b) => (b.updated || 0) - (a.updated || 0))) {
    const time = (chat.updated || 0) * 1000;
    const caption = bounds.find(([, from]) => time >= from)![0];
    groups.set(caption, [...(groups.get(caption) ?? []), chat]);
  }
  return bounds.map(([caption]) => [caption, groups.get(caption) ?? []] as [string, ChatSummary[]]).filter(([, list]) => list.length > 0);
}

export function Sidebar({ api, state, actions, searchRef, onNewChat, onSearchMessages, onSettings, onHide }:
  { api: WebApi; state: EngineState; actions: ChatActions; searchRef: RefObject<HTMLInputElement | null>; onNewChat: () => void;
    onSearchMessages: () => void; onSettings: () => void; onHide: () => void }) {
  const [query, setQuery] = useState("");
  const projects = state.code.on;
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const kind = state.chats.filter((chat) => Boolean(chat.code) === projects);
    return needle ? kind.filter((chat) => chat.title.toLowerCase().includes(needle) || chat.preview.toLowerCase().includes(needle) || (chat.root ?? "").toLowerCase().includes(needle)) : kind;
  }, [state.chats, query, projects]);
  const pinned = filtered.filter((chat) => chat.pinned);
  const groups = useMemo((): [string, ChatSummary[]][] => {
    const rest = filtered.filter((chat) => !chat.pinned);
    if (!projects) return dateGroups(rest);
    return rest.length ? [["Проекты", [...rest].sort((a, b) => (b.updated || 0) - (a.updated || 0))]] : [];
  }, [filtered, projects]);
  const rows = (chats: ChatSummary[]) => chats.map((chat) => (
    <ChatRow key={`${chat.id}-${chat.title}-${chat.pinned}`} chat={chat} active={chat.id === state.activeChatId}
      disabled={false} actions={actions} />
  ));
  return (
    <aside className="sidebar" aria-label={projects ? "Проекты" : "Чаты"}>
      <div className="nav-decor"><Decor corner="bl" /></div>
      <div className="brand">
        <Logo size={29} />
        <div className="brand-copy"><strong>PIVEN</strong></div>
        <IconButton icon="sidebar" label="Скрыть панель (Ctrl+B)" onClick={onHide} />
      </div>

      <button type="button" className="new-chat" onClick={onNewChat} title="Ctrl+N">
        <Icon name="compose" size={17} /><span>{projects ? "Новый проект" : "Новый чат"}</span>
      </button>

      <div className="side-search">
        <label className="search-field"><Icon name="search" size={15} />
          <input ref={searchRef} placeholder={projects ? "Найти проект" : "Найти чат"} value={query} onChange={(event) => setQuery(event.target.value)} />
          {query && <button type="button" aria-label="Очистить" onClick={() => setQuery("")}><Icon name="close" size={13} /></button>}
        </label>
        <button type="button" className="link-btn" onClick={onSearchMessages}><Icon name="search" size={13} /> Искать в сообщениях</button>
      </div>

      <nav className="chat-nav">
        {pinned.length > 0 && <><div className="nav-caption">Закреплённые</div>{rows(pinned)}</>}
        {groups.map(([caption, chats]) => <div key={caption} className="nav-group"><div className="nav-caption">{caption}</div>{rows(chats)}</div>)}
        {!filtered.length && <div className="nav-empty">{query.trim() ? "Ничего не найдено" : projects ? "Проектов пока нет" : "Чатов пока нет"}</div>}
      </nav>

      {state.downloads.length > 0 && (
        <div className="side-downloads" aria-label="Загрузки">
          {state.downloads.map((row) => (
            <div key={row.kind} className={`side-download ${row.state}`}>
              <div className="side-download-head">
                <Icon name={row.state === "error" ? "alert" : row.state === "done" ? "check" : "download"} size={14} />
                <span className="side-download-title" title={row.title}>{row.title || (row.kind === "model" ? "Модель" : "Голосовая модель")}</span>
                <span className="side-download-pct">{row.state === "running" ? `${row.percent}%` : row.state === "done" ? "готово" : row.state === "cancelled" ? "отменено" : "ошибка"}</span>
                {row.state === "running" && <IconButton icon="close" label="Отменить загрузку" size={13}
                  onClick={() => { void (row.kind === "model" ? api.hf_cancel() : api.voice_cancel()); }} />}
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
    </aside>
  );
}

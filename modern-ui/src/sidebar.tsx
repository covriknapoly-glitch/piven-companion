import { useMemo, useState, type RefObject } from "react";
import type { ChatSummary, EngineState } from "./bridge";
import { Icon } from "./icons";
import { IconButton, Logo, MenuButton } from "./ui";

export interface ChatActions {
  select: (chat: ChatSummary) => void;
  rename: (chat: ChatSummary, title: string) => void;
  pin: (chat: ChatSummary) => void;
  exportChat: (chat: ChatSummary, markdown: boolean) => void;
  remove: (chat: ChatSummary) => void;
}

function ChatRow({ chat, active, disabled, actions }: { chat: ChatSummary; active: boolean; disabled: boolean; actions: ChatActions }) {
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
      <button type="button" className="chat-row-main" disabled={disabled} onClick={() => actions.select(chat)} onDoubleClick={() => { setTitle(chat.title); setRenaming(true); }} title={chat.title}>
        <span className="chat-row-title">{chat.pinned && <Icon name="pin" size={12} className="pin-mark" />}{chat.title}</span>
        <span className="chat-row-preview">{chat.preview || "Пока без сообщений"}</span>
      </button>
      <MenuButton label="Действия с чатом" className="chat-row-menu" items={[
        { icon: "edit", label: "Переименовать", onClick: () => { setTitle(chat.title); setRenaming(true); } },
        { icon: "pin", label: chat.pinned ? "Открепить" : "Закрепить", onClick: () => actions.pin(chat) },
        "divider",
        { icon: "share", label: "Экспорт в Markdown", onClick: () => actions.exportChat(chat, true) },
        { icon: "file", label: "Экспорт в текст", onClick: () => actions.exportChat(chat, false) },
        "divider",
        { icon: "trash", label: "Удалить…", danger: true, disabled: disabled && !active, onClick: () => actions.remove(chat) },
      ]} />
    </div>
  );
}

export function Sidebar({ state, actions, searchRef, onNewChat, onSearchMessages, onSettings, onHide }:
  { state: EngineState; actions: ChatActions; searchRef: RefObject<HTMLInputElement | null>; onNewChat: () => void;
    onSearchMessages: () => void; onSettings: () => void; onHide: () => void }) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? state.chats.filter((chat) => chat.title.toLowerCase().includes(needle) || chat.preview.toLowerCase().includes(needle)) : state.chats;
  }, [state.chats, query]);
  const pinned = filtered.filter((chat) => chat.pinned);
  const recent = filtered.filter((chat) => !chat.pinned);
  const rows = (chats: ChatSummary[]) => chats.map((chat) => (
    <ChatRow key={`${chat.id}-${chat.title}-${chat.pinned}`} chat={chat} active={chat.id === state.activeChatId}
      disabled={state.busy && chat.id !== state.activeChatId} actions={actions} />
  ));
  const connected = state.models.length > 0;
  return (
    <aside className="sidebar" aria-label="Чаты">
      <div className="brand">
        <Logo size={44} />
        <div className="brand-copy"><strong>PIVEN</strong><small>Companion</small></div>
        <IconButton icon="sidebar" label="Скрыть панель (Ctrl+B)" onClick={onHide} />
      </div>

      <button type="button" className="new-chat" onClick={onNewChat} disabled={state.busy} title="Ctrl+N">
        <Icon name="compose" size={17} /><span>Новый чат</span>
      </button>

      <div className="side-search">
        <label className="search-field"><Icon name="search" size={15} />
          <input ref={searchRef} placeholder="Найти чат" value={query} onChange={(event) => setQuery(event.target.value)} />
          {query && <button type="button" aria-label="Очистить" onClick={() => setQuery("")}><Icon name="close" size={13} /></button>}
        </label>
        <button type="button" className="link-btn" onClick={onSearchMessages}><Icon name="search" size={13} /> Искать в сообщениях</button>
      </div>

      <nav className="chat-nav">
        {pinned.length > 0 && <><div className="nav-caption">Закреплённые</div>{rows(pinned)}</>}
        {recent.length > 0 && <><div className="nav-caption">{pinned.length ? "Остальные" : "Чаты"}</div>{rows(recent)}</>}
        {!filtered.length && <div className="nav-empty">Ничего не найдено</div>}
      </nav>

      <div className="side-foot">
        <div className="conn">
          <span className={`status-dot ${connected ? "ok" : "warn"}`} />
          <div className="conn-copy"><strong>{connected ? "llama.cpp готов" : "Нет моделей"}</strong>
            <small>{state.listening.running ? "Слушаю и смотрю" : connected ? `Моделей: ${state.models.length}` : "Скачай модель"}</small></div>
        </div>
        <IconButton icon="settings" label="Настройки (Ctrl+,)" onClick={onSettings} />
      </div>
    </aside>
  );
}

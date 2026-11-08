import { useCallback, useState } from "react";
import type { CodeMode, EngineState, WebApi } from "./bridge";
import { Icon, type IconName } from "./icons";
import { Decor, Logo, fileName, useOutsideClose } from "./ui";

type Done = (error?: string) => void;
type Reply = { ok: boolean; error?: string; cancelled?: boolean };

/** Folders of the projects started so far, the newest first, with the chosen one always among them. */
export function recentFolders(state: EngineState, limit = 5) {
  const seen = new Set<string>();
  const roots = [...state.chats]
    .filter((chat) => chat.code && chat.root)
    .sort((a, b) => (b.updated || 0) - (a.updated || 0))
    .map((chat) => chat.root as string)
    .filter((root) => !seen.has(root) && Boolean(seen.add(root)));
  const shown = roots.slice(0, limit);
  if (state.code.root && !shown.includes(state.code.root)) shown.unshift(state.code.root);
  return shown;
}

function reply(done: Done) {
  return (result: Reply) => done(result.ok || result.cancelled ? undefined : result.error);
}

function FolderRows({ state, api, onDone, onPicked }: { state: EngineState; api: WebApi; onDone: Done; onPicked?: () => void }) {
  const folders = recentFolders(state);
  return (
    <>
      {folders.map((root) => (
        <button key={root} type="button" className={`folder-row ${root === state.code.root ? "on" : ""}`} title={root}
          onClick={() => { onPicked?.(); void api.code_set({ root }).then(reply(onDone)); }}>
          <Icon name="folder" size={16} /><span className="grow" data-i18n-skip>{fileName(root)}</span>
          {root === state.code.root && <Icon name="check" size={16} />}
        </button>
      ))}
    </>
  );
}

const MODES: { id: CodeMode; name: string; short: string; hint: string; icon: IconName }[] = [
  { id: "ask", name: "Спрашивать разрешения", short: "Спрашивать", hint: "Каждую правку и команду нужно подтвердить.", icon: "chat" },
  { id: "edits", name: "Принимать правки", short: "Правки", hint: "Файлы меняются сразу, команды спрашивают разрешения.", icon: "edit" },
  { id: "plan", name: "Режим плана", short: "План", hint: "Только изучает проект и пишет план. Ничего не меняет.", icon: "file" },
  { id: "free", name: "Без разрешений", short: "Без запросов", hint: "Всё выполняется без вопросов. Запрещено всё равно: форматирование диска, системные настройки, личные данные.", icon: "alert" },
];

export function nextMode(mode: CodeMode): CodeMode {
  return MODES[(MODES.findIndex((item) => item.id === mode) + 1) % MODES.length].id;
}

function ModeRows({ state, api, onDone, onPicked }: { state: EngineState; api: WebApi; onDone: Done; onPicked: () => void }) {
  return (
    <div className="mode-rows" role="radiogroup" aria-label="Режим работы">
      {MODES.map((mode) => (
        <button key={mode.id} type="button" role="radio" aria-checked={state.code.mode === mode.id} className={`mode-row ${state.code.mode === mode.id ? "on" : ""} ${mode.id}`}
          onClick={() => { onPicked(); void api.code_set({ mode: mode.id }).then(reply(onDone)); }}>
          <Icon name={mode.icon} size={15} />
          <span><strong>{mode.name}</strong><small>{mode.hint}</small></span>
        </button>
      ))}
    </div>
  );
}

/** The empty screen of a project: pick the folder to work in, or start without one. */
export function ProjectStart({ state, api, onDone }: { state: EngineState; api: WebApi; onDone: Done }) {
  const { root } = state.code;
  return (
    <div className="intro code-start">
      <Decor corner="tr" />
      <div className="code-start-logo"><Logo size={56} /></div>
      <h2>Над чем поработаем?</h2>
      <div className="code-start-card" role="menu" aria-label="Папка проекта">
        <FolderRows state={state} api={api} onDone={onDone} />
        {root && <button type="button" className="folder-row" onClick={() => { void api.code_set({ root: "" }).then(reply(onDone)); }}>
          <Icon name="plus" size={16} /><span className="grow">Новая папка для проекта</span>
        </button>}
        <button type="button" className="folder-row pick" onClick={() => { void api.code_pick_folder().then(reply(onDone)); }}>
          <Icon name="folder" size={16} /><span className="grow">Выбрать папку…</span>
        </button>
      </div>
      <p className="code-start-note">{root ? "Агент работает только в этой папке. Опиши задачу в поле ниже." : "Папку выбирать не обязательно: агент создаст проект сам. Опиши задачу в поле ниже."}</p>
    </div>
  );
}

/** «Папка» beside the message field: the same choices as the start screen, for a project already under way. */
export function FolderChip({ state, api, onDone }: { state: EngineState; api: WebApi; onDone: Done }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useOutsideClose(open, close);
  const { root } = state.code;
  return (
    <div className="menu-anchor" ref={ref}>
      <button type="button" className={`chip-btn ${root ? "code-on" : ""}`} aria-expanded={open} onClick={() => setOpen((value) => !value)} title={root || "Папка проекта: пока не выбрана, агент создаст её сам"}>
        <Icon name="folder" size={14} />{root ? <span className="chip-text" data-i18n-skip>{fileName(root)}</span> : <span className="chip-text">Папка</span>}
      </button>
      {open && (
        <div className="menu menu-up-right code-menu" role="menu">
          <div className="menu-label">Папка проекта</div>
          <FolderRows state={state} api={api} onDone={onDone} onPicked={close} />
          <button type="button" onClick={() => { close(); void api.code_pick_folder().then(reply(onDone)); }}><Icon name="folder" size={15} /> Выбрать папку…</button>
          {root && <button type="button" onClick={() => { close(); void api.code_open_folder().then(reply(onDone)); }}><Icon name="external" size={15} /> Открыть в проводнике</button>}
          {root && <button type="button" onClick={() => { close(); void api.code_set({ root: "" }).then(reply(onDone)); }}><Icon name="plus" size={15} /> Новая папка для проекта</button>}
        </div>
      )}
    </div>
  );
}

/** The mode of the agent beside the message field. Shift+Tab goes to the next one. */
export function ModeChip({ state, api, onDone }: { state: EngineState; api: WebApi; onDone: Done }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useOutsideClose(open, close);
  const current = MODES.find((item) => item.id === state.code.mode) ?? MODES[0];
  return (
    <div className="menu-anchor" ref={ref}>
      <button type="button" className={`chip-btn mode-chip ${current.id}`} aria-expanded={open} title="Режим работы агента (Shift+Tab)" onClick={() => setOpen((value) => !value)}>
        <Icon name={current.icon} size={14} /><span className="chip-text">{current.short}</span><Icon name="chevronDown" size={14} />
      </button>
      {open && (
        <div className="menu menu-up-right code-menu" role="menu">
          <div className="menu-label">Режим работы</div>
          <ModeRows state={state} api={api} onDone={onDone} onPicked={close} />
          <div className="menu-label mode-shortcut">Shift+Tab — следующий режим</div>
        </div>
      )}
    </div>
  );
}

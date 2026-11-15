import { useEffect, useRef } from "react";
import { Icon } from "./icons";
import { Modal } from "./ui";

/** A command typed in the message field after "/". */
export interface SlashCommand { name: string; args?: string; hint: string; run: (arg: string) => void }

export const SHORTCUTS: [string, string][] = [
  ["Ctrl+N", "Новый чат"],
  ["Ctrl+Shift+N", "Новый проект"],
  ["Ctrl+K", "Поиск по чатам и сообщениям"],
  ["Ctrl+L", "Перейти к полю сообщения"],
  ["Alt+↑ / Alt+↓", "Предыдущий или следующий чат"],
  ["Ctrl+M", "Выбрать модель"],
  ["Ctrl+Shift+C", "Скопировать последний ответ"],
  ["Ctrl+B", "Показать или скрыть панель чатов"],
  ["Ctrl+D", "Браузер и файлы"],
  ["Ctrl+,", "Настройки"],
  ["Ctrl+/", "Команды и сочетания клавиш"],
  ["Esc", "Остановить ответ"],
  ["Enter / Shift+Enter", "Отправить / новая строка"],
  ["↑ в пустом поле", "Предыдущее сообщение"],
  ["Shift+Tab", "Режим агента в проекте"],
];

/** What the menu shows for the text in the field: matching commands while the name is typed, nothing once arguments start. */
export function slashMatches(draft: string, commands: SlashCommand[]) {
  if (!draft.startsWith("/") || draft.includes("\n")) return [];
  const typed = draft.slice(1);
  if (typed.includes(" ")) return [];
  const needle = typed.toLowerCase();
  return commands.filter((command) => command.name.startsWith(needle));
}

/** The command a finished line asks for, with its argument, or null when the line is an ordinary message. */
export function slashCommand(draft: string, commands: SlashCommand[]) {
  const found = /^\/(\S+)(?:\s+([\s\S]*))?$/.exec(draft.trim());
  if (!found) return null;
  const command = commands.find((item) => item.name === found[1].toLowerCase());
  return command ? { command, arg: (found[2] ?? "").trim() } : null;
}

export function SlashMenu({ matches, active, onPick }: { matches: SlashCommand[]; active: number; onPick: (command: SlashCommand) => void }) {
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => { list.current?.querySelector(".selected")?.scrollIntoView({ block: "nearest" }); }, [active]);
  return (
    <div className="menu menu-up slash-menu" role="listbox" aria-label="Команды">
      <div className="menu-label">Команды</div>
      <div className="menu-list" ref={list}>
        {matches.map((command, index) => (
          <button key={command.name} type="button" role="option" aria-selected={index === active} className={index === active ? "selected" : ""}
            onMouseDown={(event) => { event.preventDefault(); onPick(command); }}>
            <span className="slash-name"><span data-i18n-skip>/{command.name}</span>{command.args && <em> {command.args}</em>}</span>
            <span className="grow slash-hint">{command.hint}</span>
          </button>
        ))}
      </div>
      <div className="slash-foot"><Icon name="keyboard" size={13} /> Tab — дописать, Enter — выполнить</div>
    </div>
  );
}

export function HelpDialog({ commands, onClose }: { commands: SlashCommand[]; onClose: () => void }) {
  return (
    <Modal title="Команды и сочетания клавиш" subtitle="Команду можно написать в поле сообщения, начиная с «/»." onClose={onClose} width={840} className="help-modal">
      <div className="help-grid">
        <section>
          <h4>Сочетания клавиш</h4>
          <dl className="help-list">
            {SHORTCUTS.map(([keys, text]) => (
              <div key={keys}><dt><kbd>{keys}</kbd></dt><dd>{text}</dd></div>
            ))}
          </dl>
        </section>
        <section>
          <h4>Команды в чате</h4>
          <dl className="help-list">
            {commands.map((command) => (
              <div key={command.name}><dt><code><span data-i18n-skip>/{command.name}</span>{command.args && <em> {command.args}</em>}</code></dt><dd>{command.hint}</dd></div>
            ))}
          </dl>
        </section>
      </div>
    </Modal>
  );
}

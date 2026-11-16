import { useEffect, useRef, type ReactNode } from "react";
import { currentLanguage } from "./i18n";
import { Icon } from "./icons";
import { Modal } from "./ui";

/** A choice for a command's argument: what goes into the field and what the menu shows for it. */
export interface SlashOption { value: string; label?: string; hint?: string; current?: boolean }

/** A command typed in the message field after "/". Aliases are its other names, Russian ones mostly. */
export interface SlashCommand {
  name: string; aliases?: string[]; args?: string; hint: string;
  /** The fixed choices for the argument, offered while it is typed. Commands with free text have none. */
  options?: () => SlashOption[] | Promise<SlashOption[]>;
  run: (arg: string) => void;
}

/** A command found for what is typed, with the name it was found by (that name is what Tab completes). */
export interface SlashMatch { command: SlashCommand; word: string; typed: number }

/** One row of the menu above the field. */
export interface SlashRow { key: string; name: ReactNode; hint?: string; current?: boolean }

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
  ["Tab или →", "Дописать команду"],
  ["Shift+Tab", "Режим агента в проекте"],
];

const RU = "йцукенгшщзхъфывапролджэячсмитьбюё";
const EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`";

const swap = (text: string, from: string, to: string) => [...text].map((char) => { const at = from.indexOf(char); return at < 0 ? char : to[at]; }).join("");

/** The text as typed and as the same keys give it in the other layout: "/ьщвуд" is "/model", "/ntvf" is "/тема". */
function spellings(text: string) {
  const lower = text.toLowerCase();
  return [...new Set([lower, swap(lower, RU, EN), swap(lower, EN, RU)])];
}

const names = (command: SlashCommand) => [command.name, ...(command.aliases ?? [])];

function findCommand(name: string, commands: SlashCommand[]) {
  for (const spelling of spellings(name)) {
    const found = commands.find((command) => names(command).includes(spelling));
    if (found) return found;
  }
  return null;
}

/**
 * The commands for the name being typed: names that start with it first, then other names (aliases), then names
 * that only contain it, then commands whose description has a word starting with it. Nothing once a space is typed.
 */
export function slashMatches(draft: string, commands: SlashCommand[]): SlashMatch[] {
  if (!draft.startsWith("/") || /\s/.test(draft)) return [];
  // The other layout is tried only when the text as typed finds nothing, so it never adds noise to real matches.
  for (const needle of spellings(draft.slice(1))) {
    const found: { match: SlashMatch; rank: number; order: number }[] = [];
    commands.forEach((command, order) => {
      let rank = -1, match: SlashMatch = { command, word: command.name, typed: 0 };
      for (const [at, word] of names(command).entries()) {
        const here = word.startsWith(needle) ? (at ? 1 : 0) : needle.length > 1 && word.includes(needle) ? 2 : -1;
        if (here >= 0 && (rank < 0 || here < rank)) { rank = here; match = { command, word, typed: here < 2 ? needle.length : 0 }; }
      }
      if (rank < 0 && needle.length > 2 && command.hint.toLowerCase().split(/[^a-zа-яё]+/).some((word) => word.startsWith(needle))) rank = 3;
      if (rank >= 0) found.push({ match, rank, order });
    });
    if (found.length) return found.sort((a, b) => a.rank - b.rank || a.order - b.order).map((item) => item.match);
  }
  return [];
}

/** The command whose argument is being typed ("/theme гр" gives theme and "гр"), or null while its name is typed. */
export function slashArgument(draft: string, commands: SlashCommand[]) {
  const found = /^\/(\S+) ([^\n]*)$/.exec(draft);
  const command = found ? findCommand(found[1], commands) : null;
  return found && command ? { command, word: found[1], arg: found[2] } : null;
}

/** The choices that fit the typed argument, those that start with it first. */
export function optionMatches(arg: string, options: SlashOption[]) {
  const typed = arg.trim();
  if (!typed) return options;
  for (const needle of spellings(typed)) {
    const found: { option: SlashOption; rank: number; order: number }[] = [];
    options.forEach((option, order) => {
      let rank = -1;
      for (const text of [option.label ?? option.value, option.value]) {
        const lower = text.toLowerCase();
        const here = lower.startsWith(needle) || lower.split(/[\s/:._-]+/).some((word) => word.startsWith(needle)) ? 0 : needle.length > 1 && lower.includes(needle) ? 1 : -1;
        if (here >= 0 && (rank < 0 || here < rank)) rank = here;
      }
      if (rank >= 0) found.push({ option, rank, order });
    });
    if (found.length) return found.sort((a, b) => a.rank - b.rank || a.order - b.order).map((item) => item.option);
  }
  return [];
}

/** The command a finished line asks for, with its argument, or null when the line is an ordinary message. */
export function slashCommand(draft: string, commands: SlashCommand[]) {
  const found = /^\/(\S+)(?:\s+([\s\S]*))?$/.exec(draft.trim());
  if (!found) return null;
  const command = findCommand(found[1], commands);
  return command ? { command, arg: (found[2] ?? "").trim() } : null;
}

/** "/model" with the part already typed in a brighter colour. */
export function SlashName({ match }: { match: SlashMatch }) {
  const { word, typed, command } = match;
  return (
    <span className="slash-name">
      <span data-i18n-skip>/{typed ? <><b>{word.slice(0, typed)}</b>{word.slice(typed)}</> : word}</span>
      {command.args && <em> {command.args}</em>}
    </span>
  );
}

export function SlashMenu({ title, rows, active, empty, onPick }:
  { title: string; rows: SlashRow[]; active: number; empty?: string; onPick: (index: number) => void }) {
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => { list.current?.querySelector(".selected")?.scrollIntoView({ block: "nearest" }); }, [active, rows.length]);
  return (
    <div className="menu menu-up slash-menu" role="listbox" aria-label={title}>
      <div className="menu-label">{title}</div>
      <div className="menu-list" ref={list}>
        {rows.map((row, index) => (
          <button key={row.key} type="button" role="option" aria-selected={index === active} className={index === active ? "selected" : ""}
            onMouseDown={(event) => { event.preventDefault(); onPick(index); }}>
            {row.name}
            <span className="grow slash-hint">{row.hint}</span>
            {row.current && <Icon name="check" size={14} />}
          </button>
        ))}
        {!rows.length && empty && <p className="slash-empty">{empty}</p>}
      </div>
      <div className="slash-foot"><Icon name="keyboard" size={13} /> {rows.length ? "Tab или → — дописать, Enter — выполнить" : "Enter — выполнить, Esc — закрыть"}</div>
    </div>
  );
}

/** What a command with free text after it does, shown while that text is typed. */
export function SlashUsage({ command, word }: { command: SlashCommand; word: string }) {
  return (
    <div className="menu menu-up slash-menu slash-usage" role="status">
      <div className="slash-usage-line">
        <span className="slash-name"><span data-i18n-skip>/{word}</span>{command.args && <em> {command.args}</em>}</span>
        <span className="slash-hint">{command.hint}</span>
      </div>
      <div className="slash-foot"><Icon name="keyboard" size={13} /> Enter — выполнить, Esc — закрыть</div>
    </div>
  );
}

export function HelpDialog({ commands, onClose }: { commands: SlashCommand[]; onClose: () => void }) {
  // The Russian names help only someone who types in Russian.
  const aliases = currentLanguage() === "ru";
  return (
    <Modal title="Команды и сочетания клавиш" subtitle="Команду можно написать в поле сообщения, начиная с «/». Tab дописывает команду и её вариант." onClose={onClose} width={840} className="help-modal">
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
              <div key={command.name}>
                <dt><code><span data-i18n-skip>/{command.name}</span>{command.args && <em> {command.args}</em>}</code></dt>
                <dd>{command.hint}{aliases && command.aliases?.length ? <small className="help-alias" data-i18n-skip>{command.aliases.map((alias) => `/${alias}`).join("  ")}</small> : null}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </Modal>
  );
}

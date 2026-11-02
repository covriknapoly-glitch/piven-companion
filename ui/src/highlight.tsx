import type { ReactNode } from "react";

const HASH_COMMENTS = new Set(["python", "py", "bash", "sh", "shell", "zsh", "powershell", "ps1", "ruby", "rb", "yaml", "yml", "toml", "perl", "r", "dockerfile", "makefile", "ini", "conf", "nim", "elixir"]);
const DASH_COMMENTS = new Set(["sql", "lua", "haskell", "hs"]);

const KEYWORDS = new Set(`
  and as assert async await break case catch class const continue def default del delete do elif else enum except export extends
  finally fn for from func function global go if impl import in instanceof interface is lambda let loop match mod module mut new
  nonlocal not or package pass private protected pub public raise readonly return self static struct super switch this throw throws
  trait try type typeof unsafe use using var void where while with yield select insert update delete into values create table
  drop alter join left right inner outer on group by order having limit as begin end then local function repeat until
  true false null none nil undefined True False None
`.split(/\s+/).filter(Boolean));

type Kind = "comment" | "string" | "number" | "keyword" | "type" | "call" | "deco" | "punct";

function pattern(lang: string) {
  const comment = HASH_COMMENTS.has(lang) ? String.raw`#[^\n]*`
    : DASH_COMMENTS.has(lang) ? String.raw`--[^\n]*`
    : String.raw`\/\/[^\n]*|\/\*[\s\S]*?\*\/|<!--[\s\S]*?-->` + (lang ? "" : String.raw`|#(?![{\[])[^\n]*`);
  return new RegExp([
    `(?<comment>${comment})`,
    String.raw`(?<string>"""[\s\S]*?"""|'''[\s\S]*?'''|\`(?:\\[\s\S]|[^\\\`])*\`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')`,
    String.raw`(?<deco>@[A-Za-z_][\w.]*)`,
    String.raw`(?<number>\b(?:0x[\da-fA-F]+|\d+(?:\.\d+)?(?:e[+-]?\d+)?)\b)`,
    String.raw`(?<word>[A-Za-z_][\w]*)(?<call>\s*\()?`,
  ].join("|"), "g");
}

export function highlight(code: string, language: string): ReactNode[] {
  const lang = language.trim().toLowerCase();
  const out: ReactNode[] = [];
  const regex = pattern(lang);
  let last = 0;
  let key = 0;
  const push = (text: string, kind?: Kind) => {
    if (!text) return;
    out.push(kind ? <span key={key++} className={`tok-${kind}`}>{text}</span> : text);
  };
  for (const match of code.matchAll(regex)) {
    const groups = match.groups ?? {};
    const start = match.index ?? 0;
    push(code.slice(last, start));
    if (groups.comment) push(groups.comment, "comment");
    else if (groups.string) push(groups.string, "string");
    else if (groups.deco) push(groups.deco, "deco");
    else if (groups.number) push(groups.number, "number");
    else if (groups.word) {
      const word = groups.word;
      const kind: Kind | undefined = KEYWORDS.has(word) || KEYWORDS.has(word.toLowerCase()) && lang === "sql" ? "keyword"
        : groups.call ? "call"
        : /^[A-Z][a-z]\w*$/.test(word) ? "type"
        : undefined;
      push(word, kind);
      push(groups.call ?? "");
    }
    last = start + match[0].length;
  }
  push(code.slice(last));
  return out;
}

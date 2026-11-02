import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { highlight } from "./highlight";
import { Icon } from "./icons";

/**
 * Small Markdown renderer for model answers. It builds React elements only
 * (never raw HTML), so text from the model cannot inject markup or scripts.
 * Links never navigate the app window: http(s) links go to the handler in
 * LinkContext (the built-in browser pane), anything else is only shown.
 */

export const LinkContext = createContext<((url: string) => void) | null>(null);

function MdLink({ label, url }: { label: string; url: string }) {
  const open = useContext(LinkContext);
  if (!open || !/^https?:\/\//i.test(url)) return <span className="md-link" title={url}>{label}</span>;
  return <button type="button" className="md-link" title={url} onClick={() => open(url)}>{label}</button>;
}

type Block =
  | { kind: "code"; lang: string; text: string }
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; ordered: boolean; start: number; items: string[] }
  | { kind: "quote"; text: string }
  | { kind: "rule" }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "paragraph"; text: string };

const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const splitRow = (line: string) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());

function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const fence = line.match(/^\s*```\s*([\w+#.-]*)\s*$/);
    if (fence) {
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) body.push(lines[index++]);
      index += 1;
      blocks.push({ kind: "code", lang: fence[1], text: body.join("\n") });
      continue;
    }
    if (!line.trim()) { index += 1; continue; }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) { blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] }); index += 1; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { blocks.push({ kind: "rule" }); index += 1; continue; }
    if (/^\s*\|/.test(line) && index + 1 < lines.length && TABLE_RULE.test(lines[index + 1])) {
      const header = splitRow(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && /^\s*\|/.test(lines[index])) rows.push(splitRow(lines[index++]));
      blocks.push({ kind: "table", header, rows });
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (index < lines.length && /^\s*>/.test(lines[index])) body.push(lines[index++].replace(/^\s*>\s?/, ""));
      blocks.push({ kind: "quote", text: body.join("\n") });
      continue;
    }
    const bullet = /^\s*(?:[-*•+])\s+/;
    const numbered = /^\s*\d+[.)]\s+/;
    if (bullet.test(line) || numbered.test(line)) {
      const ordered = numbered.test(line);
      const pattern = ordered ? numbered : bullet;
      const start = ordered ? parseInt(line.trim(), 10) || 1 : 1;
      const items: string[] = [];
      while (index < lines.length) {
        if (pattern.test(lines[index])) items.push(lines[index].replace(pattern, ""));
        else if (/^\s{2,}\S/.test(lines[index]) && items.length) items[items.length - 1] += " " + lines[index].trim();
        // Models often put blank lines between list items; keep them in one list.
        else if (!lines[index].trim() && index + 1 < lines.length && pattern.test(lines[index + 1])) { index += 1; continue; }
        else break;
        index += 1;
      }
      blocks.push({ kind: "list", ordered, start, items });
      continue;
    }
    const body: string[] = [];
    while (index < lines.length && lines[index].trim() && !/^\s*```/.test(lines[index]) && !/^#{1,4}\s/.test(lines[index])
      && !bullet.test(lines[index]) && !numbered.test(lines[index]) && !/^\s*>/.test(lines[index])) body.push(lines[index++]);
    blocks.push({ kind: "paragraph", text: body.join("\n") });
  }
  return blocks;
}

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\n]+\*)|(\[[^\]\n]+\]\([^)\s]+\))/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  INLINE.lastIndex = 0;
  while ((match = INLINE.exec(text))) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${match.index}`;
    if (token.startsWith("`")) nodes.push(<code key={key} className="md-inline-code">{token.slice(1, -1)}</code>);
    else if (token.startsWith("**") || token.startsWith("__")) nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith("*")) nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    else {
      const link = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      nodes.push(<MdLink key={key} label={link?.[1] ?? token} url={link?.[2] ?? ""} />);
    }
    last = match.index + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function CodeBlock({ lang, text, onCopy }: { lang: string; text: string; onCopy: (text: string) => void }) {
  const [copied, setCopied] = useState(false);
  const tokens = useMemo(() => highlight(text, lang), [text, lang]);
  return (
    <div className="md-code">
      <div className="md-code-head" data-i18n>
        <span>{lang || "код"}</span>
        <button type="button" onClick={() => { onCopy(text); setCopied(true); window.setTimeout(() => setCopied(false), 1400); }}>
          <Icon name={copied ? "check" : "copy"} size={13} /> {copied ? "Скопировано" : "Копировать"}
        </button>
      </div>
      <pre><code>{tokens}</code></pre>
    </div>
  );
}

export function Markdown({ text, onCopy }: { text: string; onCopy: (text: string) => void }) {
  return (
    <div className="md" data-i18n-skip>
      {parseBlocks(text).map((block, index) => {
        const key = `b${index}`;
        switch (block.kind) {
          case "code": return <CodeBlock key={key} lang={block.lang} text={block.text} onCopy={onCopy} />;
          case "heading": {
            const Tag = (["h3", "h3", "h4", "h5"] as const)[block.level - 1];
            return <Tag key={key}>{renderInline(block.text, key)}</Tag>;
          }
          case "list": {
            const items = block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item, `${key}-${itemIndex}`)}</li>);
            return block.ordered ? <ol key={key} start={block.start}>{items}</ol> : <ul key={key}>{items}</ul>;
          }
          case "quote": return <blockquote key={key}>{renderInline(block.text, key)}</blockquote>;
          case "rule": return <hr key={key} />;
          case "table": return (
            <div key={key} className="md-table"><table>
              <thead><tr>{block.header.map((cell, cellIndex) => <th key={cellIndex}>{renderInline(cell, `${key}-h${cellIndex}`)}</th>)}</tr></thead>
              <tbody>{block.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{renderInline(cell, `${key}-${rowIndex}-${cellIndex}`)}</td>)}</tr>)}</tbody>
            </table></div>
          );
          default: return <p key={key}>{renderInline(block.text, key)}</p>;
        }
      })}
    </div>
  );
}

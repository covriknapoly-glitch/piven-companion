/**
 * Interface languages. The interface is written in Russian; for English, Chinese and Spanish this module
 * translates what is on screen: text nodes and the placeholder / title / aria-label attributes, by the
 * dictionary in i18n/strings.json (Russian source → [en, zh, es]). Texts with values in them are matched as
 * patterns ("Моделей: {0}"). Chat messages and model answers (marked data-i18n-skip) are never touched.
 */
import strings from "./i18n/strings.json";

export type Language = "ru" | "en" | "zh" | "es";
export const LANGUAGES: [Language, string][] = [["ru", "Русский"], ["en", "English"], ["zh", "中文（简体）"], ["es", "Español"]];
const COLUMN: Record<Exclude<Language, "ru">, number> = { en: 0, zh: 1, es: 2 };
const ATTRIBUTES = ["placeholder", "title", "aria-label"];
const CYRILLIC = /[А-Яа-яЁё]/;

const dictionary = strings as unknown as Record<string, [string, string, string]>;
// Longer patterns first: "Не удалось получить ответ модели: запрос не поместился…{0}" before "…модели: {0}".
const patterns = Object.keys(dictionary).filter((key) => /\{\d\}/.test(key)).sort((a, b) => b.length - a.length).map((key) => ({
  key,
  test: new RegExp("^" + key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\\\{(\d)\\\}/g, "(?<p$1>.+?)") + "$", "s"),
}));

let current: Language = "ru";
const originals = new WeakMap<Node, string>();           // a text node's Russian text
const originalAttributes = new WeakMap<Element, Record<string, string>>();
let observer: MutationObserver | null = null;


/** The translation of one Russian text in the current language, or null when there is none. */
export function translate(text: string): string | null {
  if (current === "ru" || !CYRILLIC.test(text)) return null;
  const clean = text.replace(/\s+/g, " ").trim();
  const column = COLUMN[current];
  const exact = dictionary[clean];
  if (exact) return text.replace(clean.length === text.length ? text : text.trim(), exact[column]);
  for (const { key, test } of patterns) {
    const match = test.exec(clean);
    if (!match) continue;
    let result = dictionary[key][column];
    Object.entries(match.groups ?? {}).forEach(([name, value]) => {
      const word = value.trim();
      // an inserted text is translated on its own too, also when it is a pattern ("…: Слайд 4 должен быть…")
      const inner = word === clean ? null : translate(word);
      // a known word written in lower case inside a sentence ("Размышление: низкий") keeps that case translated
      const capital: string[] | undefined = inner ? undefined : dictionary[word.charAt(0).toUpperCase() + word.slice(1)];
      const translated = inner ?? (capital ? capital[column].charAt(0).toLowerCase() + capital[column].slice(1) : value);
      result = result.replace(`{${name.slice(1)}}`, translated);
    });
    return text.replace(text.trim(), result);
  }
  return null;
}

// Interface parts inside an answer (a code block's copy button) opt back in with data-i18n.
// A text field's own placeholder and title are translated, only the text typed into it is not.
const skipped = (node: Node) => {
  const element = node instanceof Element ? (node.matches("textarea") ? node.parentElement : node) : node.parentElement;
  const owner = element?.closest("[data-i18n-skip], [data-i18n], textarea, script, style");
  return Boolean(owner && !owner.hasAttribute("data-i18n"));
};

function applyText(node: Text) {
  if (skipped(node)) return;
  const source = originals.get(node) ?? node.data;
  if (!originals.has(node)) {
    if (!CYRILLIC.test(source)) return;
    originals.set(node, source);
  }
  const translated = current === "ru" ? source : translate(source) ?? source;
  if (node.data !== translated) node.data = translated;
}

function applyAttributes(element: Element) {
  if (skipped(element)) return;
  let saved = originalAttributes.get(element);
  for (const name of ATTRIBUTES) {
    const value = element.getAttribute(name);
    if (value === null) continue;
    if (!saved || !(name in saved)) {
      if (!CYRILLIC.test(value)) continue;
      saved = { ...(saved ?? {}), [name]: value };
      originalAttributes.set(element, saved);
    }
    const translated = current === "ru" ? saved[name] : translate(saved[name]) ?? saved[name];
    if (value !== translated) element.setAttribute(name, translated);
  }
}

function applyTree(root: Node) {
  if (root.nodeType === Node.TEXT_NODE) { applyText(root as Text); return; }
  if (!(root instanceof Element)) return;
  applyAttributes(root);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) applyText(node as Text); else applyAttributes(node as Element);
  }
}

/** Switch the interface language (and keep translating whatever React renders next). */
export function setLanguage(language: Language) {
  current = language;
  document.documentElement.lang = language === "zh" ? "zh-CN" : language;
  applyTree(document.body);
  observer?.takeRecords();  // our own rewrites are not new source texts
  if (observer) return;
  observer = new MutationObserver((records) => {
    for (const record of records) {
      try {  // one odd node must never stop the translation of everything after it
        if (record.type === "characterData") {
          originals.delete(record.target);  // React wrote a new source text into this node
          applyText(record.target as Text);
        } else if (record.type === "attributes" && record.target instanceof Element) {
          const saved = originalAttributes.get(record.target);
          if (saved && record.attributeName) delete saved[record.attributeName];
          applyAttributes(record.target);
        } else {
          record.addedNodes.forEach(applyTree);
        }
      } catch (error) {
        console.warn("translation skipped a node", error);
      }
    }
    observer?.takeRecords();  // drop the records our own rewrites just produced
  });
  observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRIBUTES });
}

/** Russian unless the user picked another language (WebView2 reports the system language, often en-US). */
export function defaultLanguage(): Language {
  return "ru";
}

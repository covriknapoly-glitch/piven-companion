/**
 * UI-to-engine contract. In the desktop window pywebview injects
 * `window.pywebview.api` (web_companion.pyw → WebApi), which works on the same
 * chats and settings as the Qt window through companion_core.
 */
export type ChatRole = "user" | "assistant" | "system" | "computer";

export interface DialogueItem {
  role: ChatRole;
  text: string;
  images: string[];
}

export interface ChatSummary {
  id: string;
  title: string;
  pinned: boolean;
  count: number;
}

export interface EngineSettings {
  model: string;
  speechEnabled: boolean;
  projectRoot: string;
  comfyUrl: string;
  voice: string;
  theme: string;
  systemPrompt: string;
  integrations: Record<string, boolean>;
  thinkingLevel: string | boolean;
}

export interface EngineState {
  version: number;
  activeChatId: string;
  chats: ChatSummary[];
  items: DialogueItem[];
  chatTitle: string;
  busy: boolean;
  activity: string;
  status: string;
  reasoning: string;
  notice: string;
  models: string[];
  modelsError: string;
  settings: EngineSettings;
}

export type PollResult = EngineState | { version: number; unchanged: true };

export interface CommandResult {
  ok: boolean;
  error?: string;
  queued?: boolean;
  route?: string;
}

export interface SettingsDetails {
  systemPrompt: string;
  defaultSystemPrompt: string;
  speechEnabled: boolean;
  voice: string;
  voices: string[];
  screenInterval: number;
  micDevice: string;
  micSensitivity: number;
  microphones: string[];
  micError: string;
  comfyUrl: string;
  comfyWorkflow: string;
  projectRoot: string;
  twitchChannel: string;
  integrations: Record<string, boolean>;
  dataDir: string;
}

export type ThinkingValue = string | boolean;

export interface SettingsResult { ok: boolean; errors: Record<string, string>; saved: string[] }

interface WebApi {
  poll(knownVersion: number): Promise<PollResult>;
  state(): Promise<EngineState>;
  refresh_models(): Promise<EngineState>;
  send(text: string): Promise<CommandResult>;
  interrupt(): Promise<CommandResult>;
  select_chat(chatId: string): Promise<CommandResult>;
  new_chat(): Promise<CommandResult>;
  set_model(name: string): Promise<CommandResult>;
  set_speech(enabled: boolean): Promise<CommandResult>;
  route_hint(text: string): Promise<{ route: string; label: string }>;
  set_title_theme(dark: boolean): Promise<CommandResult>;
  settings_details(): Promise<SettingsDetails>;
  update_settings(patch: Record<string, unknown>): Promise<SettingsResult>;
  thinking_options(model: string): Promise<{ values: ThinkingValue[]; default: ThinkingValue | null; current: ThinkingValue; error: string }>;
  set_thinking(model: string, value: ThinkingValue): Promise<CommandResult>;
  pick_path(kind: "folder" | "workflow"): Promise<string>;
  open_data_folder(what?: "folder" | "log"): Promise<CommandResult>;
  rename_chat(chatId: string, title: string): Promise<CommandResult>;
  pin_chat(chatId: string, pinned: boolean): Promise<CommandResult>;
  image_data(path: string): Promise<string>;
  open_file(path: string): Promise<CommandResult>;
  copy_text(text: string): Promise<CommandResult>;
}

declare global {
  interface Window {
    pywebview?: { api: WebApi };
  }
}

/** Resolves with the API once pywebview has injected it, or null outside the desktop window. */
export function waitForEngine(timeoutMs = 4000): Promise<WebApi | null> {
  if (window.pywebview?.api) return Promise.resolve(window.pywebview.api);
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => resolve(window.pywebview?.api ?? null), timeoutMs);
    window.addEventListener("pywebviewready", () => {
      window.clearTimeout(timer);
      resolve(window.pywebview?.api ?? null);
    }, { once: true });
  });
}

export const isUnchanged = (result: PollResult): result is { version: number; unchanged: true } =>
  "unchanged" in result && result.unchanged === true;

export type { WebApi };

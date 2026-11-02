/**
 * UI-to-engine contract. In the desktop window pywebview injects
 * `window.pywebview.api` (web_companion.pyw → WebApi), which works on the same
 * chats and settings as the Qt window through companion_core.
 */
export type ChatRole = "user" | "assistant" | "system" | "computer" | "poll" | "error";

export interface DialogueItem {
  role: ChatRole;
  text: string;
  images: string[];
  undo?: number;   // files and folders the request behind this answer made, which its undo button deletes
}

export interface ChatSummary {
  id: string;
  title: string;
  pinned: boolean;
  count: number;
  preview: string;
  busy?: boolean;      // an answer is being written in this chat (it may be in the background)
  unread?: boolean;    // an answer arrived while another chat was open
  model?: string;
  updated?: number;    // last change, seconds since the epoch; 0 for chats saved before it was tracked
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

export interface ListenOptions { mic: boolean; loopback: boolean; screen: boolean; proactive: boolean }

export interface DownloadConfirm { id: string; kind: "download"; url: string; destination: string }

export interface EngineState {
  version: number;
  activeChatId: string;
  chats: ChatSummary[];
  items: DialogueItem[];
  chatTitle: string;
  busy: boolean;
  busySince: number;
  listening: { running: boolean; options: ListenOptions };
  call: { speaking: boolean; hearing: boolean; muted: boolean };
  confirm: DownloadConfirm | null;
  downloads: DownloadRow[];
  browserRequest: { url: string; nonce: number } | null;
  activity: string;
  status: string;
  reasoning: string;
  notice: string;
  models: string[];
  modelsError: string;
  settings: EngineSettings;
}

export type ParamValue = number | string | boolean;
export interface ModelParams {
  model: string; defaults: Record<string, ParamValue>; limits: Record<string, [number, number]>; choices: Record<string, string[]>;
  presets: Record<string, Record<string, ParamValue>>; serverKeys: string[]; all: Record<string, ParamValue>; own: Record<string, ParamValue>;
  effective: Record<string, ParamValue>; autoTitles: boolean;
}
export interface ProviderRow { id: string; title: string; local: boolean; needsKey: boolean; enabled: boolean; url: string; defaultUrl: string; hasKey: boolean; models: number; error: string; installed: boolean; site: string }
export interface McpServer { name: string; command: string; url: string; env: Record<string, string>; enabled: boolean; error?: string; tools?: number | null }
export interface SkillRow { name: string; folder: string; description: string; builtin: boolean; body: string }
export interface ToolsStatus { enabled: boolean; servers: McpServer[]; skills: SkillRow[] }
export interface CodeRun { ok: boolean; stdout?: string; stderr?: string; exitCode?: number | null; seconds?: number; error?: string }
export interface Slide { title: string; texts: string[]; images: string[]; background: string }
export interface MemoryStatus {
  enabled: boolean; facts: { id: number; text: string; created: number }[]; counts: { facts: number; exchanges: number; withMeaning: number };
  modelReady: boolean; modelSize: string; modelName: string; job: { state?: string; percent?: number; message?: string };
}
export interface DownloadRow { kind: "model" | "voice"; title: string; state: "running" | "done" | "error" | "cancelled"; percent: number; message: string }

export type PollResult = EngineState | { version: number; unchanged: true };

export interface CommandResult {
  ok: boolean;
  error?: string;
  queued?: boolean;
  route?: string;
  cancelled?: boolean;
  path?: string;
}

export interface SettingsDetails {
  systemPrompt: string;
  defaultSystemPrompt: string;
  speechEnabled: boolean;
  voice: string;
  voices: [string, string][];
  voiceSample: string;
  voiceSampleText: string;
  screenInterval: number;
  micDevice: string;
  micSensitivity: number;
  bargeIn: boolean;
  closeToTray: boolean;
  maxLoadedModels: number;
  notifications: boolean;
  microphones: string[];
  micError: string;
  comfyUrl: string;
  comfyWorkflow: string;
  comfyVideoWorkflow: string;
  projectRoot: string;
  twitchChannel: string;
  integrations: Record<string, boolean>;
  dataDir: string;
}

export type ThinkingValue = string | boolean;
export interface ThinkingOptions { values: ThinkingValue[]; default: ThinkingValue | null; current: ThinkingValue; error: string }
export interface SettingsResult { ok: boolean; errors: Record<string, string>; saved: string[] }
export interface SearchHit { chatId: string; chatTitle: string; index: number; role: ChatRole; excerpt: string }
export interface TwitchStatus { status: string; channel: string; enabled: boolean; maxChars: number }
export interface HfModel { id: string; downloads?: number; likes?: number; gated: boolean; arch?: string }
export interface HfFile { path: string; size?: number }
export interface BrowserState { url: string; title: string; loading: boolean; canBack: boolean; canForward: boolean; notice: string }
export type VoiceKind = "asr" | "tts";
export interface DiskUsage { ok: boolean; error?: string; models: { name: string; bytes: number }[]; voiceModels: number; engines: { label: string; bytes: number }[] }
export interface VoiceModel { id: string; title: string; note: string; license: string; source: string; size: string; memory: number; installed: boolean; custom: boolean; engine: string; bytes: number }
export interface VoiceSearchHit { id: string; title?: string; note?: string; downloads: number; gated: boolean; engine: string; engineLabel: string; reason: string; license?: string; nonCommercial?: boolean }
export interface VoiceDetails { ok: boolean; error?: string; supported?: boolean; reason?: string; engine?: string; mode?: "custom" | "design"; voices?: string[]; files?: (HfFile & { label?: string })[]; bytes?: number; note?: string; license?: string }
export interface MemoryEstimate { total: number; weights: number; kv: number; other: number; speed?: number; measured?: boolean }
export interface ModelFeatures { vision: boolean; thinking: boolean; context: number }
export interface ModelMemory { gpu: number; context: number; models: Record<string, MemoryEstimate>; voiceReserved?: number; features?: Record<string, ModelFeatures> }
export interface ContextUsage {
  ok: boolean; error?: string; model: string; cloud: boolean; used: number; limit: number; turns: number; images: number; toolCount: number; serversWaiting: string[];
  parts: { system: number; summary: number; skills: number; tools: number; history: number; images: number };
  historyShare: number; compress: boolean;   // the part of the window the conversation may take, and whether older turns are summarised
}
export interface VoiceStatus {
  asr: { models: VoiceModel[]; engine: boolean; engineNote: string; selected: string };
  tts: { models: VoiceModel[]; engine: boolean; engineNote: string; selected: string };
  gpu: number;
  job: { kind: VoiceKind | ""; id: string; state: "idle" | "running" | "done" | "error" | "cancelled"; percent: number; message: string; error: string; installed?: string };
}
export interface HfStatus { state: "idle" | "running" | "done" | "error" | "cancelled"; percent: number; message: string; tag: string; path: string; error: string }

interface WebApi {
  poll(knownVersion: number): Promise<PollResult>;
  state(): Promise<EngineState>;
  refresh_models(): Promise<EngineState>;
  send_message(text: string, imagePaths: string[]): Promise<CommandResult>;
  interrupt(): Promise<CommandResult>;
  select_chat(chatId: string): Promise<CommandResult>;
  new_chat(): Promise<CommandResult>;
  rename_chat(chatId: string, title: string): Promise<CommandResult>;
  pin_chat(chatId: string, pinned: boolean): Promise<CommandResult>;
  delete_chat(chatId: string): Promise<CommandResult>;
  export_chat(chatId: string, markdown: boolean): Promise<CommandResult>;
  search_messages(query: string): Promise<SearchHit[]>;
  retry_last(): Promise<CommandResult>;
  edit_message(index: number, text: string): Promise<CommandResult>;
  undo_files(index: number): Promise<CommandResult>;
  speak(text: string): Promise<CommandResult>;
  set_model(name: string): Promise<CommandResult>;
  set_speech(enabled: boolean): Promise<CommandResult>;
  route_hint(text: string): Promise<{ route: string; label: string }>;
  image_data(path: string): Promise<string>;
  open_file(path: string): Promise<CommandResult>;
  save_copy(path: string): Promise<CommandResult>;
  copy_text(text: string): Promise<CommandResult>;
  pick_images(): Promise<string[]>;
  save_upload(name: string, dataBase64: string): Promise<CommandResult>;
  start_listening(options: ListenOptions): Promise<CommandResult>;
  stop_listening(): Promise<CommandResult>;
  answer_confirmation(id: string, approved: boolean): Promise<CommandResult>;
  set_title_theme(dark: boolean): Promise<CommandResult>;
  settings_details(): Promise<SettingsDetails>;
  update_settings(patch: Record<string, unknown>): Promise<SettingsResult>;
  set_mic_muted(muted: boolean): Promise<CommandResult>;
  thinking_options(model: string): Promise<ThinkingOptions>;
  set_thinking(model: string, value: ThinkingValue): Promise<CommandResult>;
  pick_path(kind: "folder" | "workflow" | "audio"): Promise<string>;
  open_data_folder(what?: "folder" | "log"): Promise<CommandResult>;
  twitch_status(): Promise<TwitchStatus>;
  open_twitch_help(): Promise<CommandResult>;
  open_url(url: string): Promise<CommandResult>;
  browser_place(x: number, y: number, width: number, height: number, visible: boolean): Promise<CommandResult>;
  browser_go(url: string): Promise<CommandResult>;
  browser_command(name: "back" | "forward" | "reload" | "stop"): Promise<CommandResult>;
  browser_state(): Promise<BrowserState>;
  twitch_send(channel: string, message: string, token: string): Promise<CommandResult & { message?: string; status?: string }>;
  hf_search(query: string, token: string): Promise<{ ok: boolean; error?: string; models: HfModel[] }>;
  hf_files(repoId: string, token: string): Promise<{ ok: boolean; error?: string; files: HfFile[]; tag?: string }>;
  hf_suggest_tag(repoId: string, filePath: string): Promise<string>;
  hf_start(repoId: string, record: HfFile, tag: string, token: string): Promise<CommandResult>;
  hf_status(): Promise<HfStatus>;
  hf_cancel(): Promise<CommandResult>;
  voice_status(): Promise<VoiceStatus>;
  voice_install(kind: VoiceKind, modelId: string, extra?: { file?: HfFile; repo?: string; size?: number; engine?: string; voices?: string[] }, token?: string): Promise<CommandResult>;
  voice_search(kind: VoiceKind, query: string, token?: string): Promise<{ ok: boolean; error?: string; models: VoiceSearchHit[] }>;
  voice_details(kind: VoiceKind, repo: string, engine: string, token?: string): Promise<VoiceDetails>;
  voice_select(kind: VoiceKind, modelId: string): Promise<CommandResult & { restart?: boolean }>;
  restart_app(): Promise<CommandResult>;
  model_params(model: string): Promise<ModelParams>;
  set_model_params(scope: string, values: Record<string, ParamValue>, replace: boolean): Promise<CommandResult>;
  set_auto_titles(enabled: boolean): Promise<CommandResult>;
  reset_settings(): Promise<CommandResult>;
  set_language(language: string): Promise<CommandResult>;
  recommended_model(): Promise<{ ok: boolean; repo?: string; record?: Record<string, unknown>; tag?: string; size?: number; why?: string; error?: string }>;
  providers_status(): Promise<{ providers: ProviderRow[] }>;
  tools_status(): Promise<ToolsStatus>;
  run_code(language: string, code: string, stdin: string): Promise<CodeRun>;
  memory_status(): Promise<MemoryStatus>;
  memory_set_enabled(enabled: boolean): Promise<CommandResult>;
  memory_add_fact(text: string): Promise<CommandResult>;
  memory_delete(id: number): Promise<CommandResult>;
  memory_clear(kind: string): Promise<CommandResult>;
  memory_download_model(repo: string, file: string, size: number): Promise<CommandResult>;
  memory_search_models(query: string): Promise<{ ok: boolean; error?: string; models: { id: string; downloads: number }[] }>;
  memory_model_files(repo: string): Promise<{ ok: boolean; error?: string; files: HfFile[] }>;
  memory_cancel(): Promise<CommandResult>;
  twitch_poll(channel: string, question: string, choices: string[], seconds: number, token: string): Promise<{ ok: boolean; message?: string; error?: string }>;
  answer_poll(question: string, choice: string): Promise<CommandResult>;
  presentation_slides(path: string): Promise<{ ok: boolean; slides: Slide[]; error?: string }>;
  set_tools_enabled(enabled: boolean): Promise<CommandResult>;
  save_mcp_server(entry: McpServer, oldName: string): Promise<{ ok: boolean; error?: string; tools?: number }>;
  delete_mcp_server(name: string): Promise<CommandResult>;
  save_skill(name: string, description: string, instructions: string): Promise<{ ok: boolean; error?: string; folder?: string }>;
  delete_skill(folder: string): Promise<CommandResult>;
  set_provider(provider: string, enabled: boolean | null, url: string | null, key: string | null): Promise<{ ok: boolean; error: string; models: number }>;
  model_description(repoId: string, token: string): Promise<{ text: string; source: string }>;
  model_logos(names: string[], authors?: Record<string, string>, archs?: Record<string, string>): Promise<Record<string, string>>;
  model_memory(names?: string[]): Promise<ModelMemory>;
  context_usage(): Promise<ContextUsage>;
  hf_memory(repoId: string, filePath: string, size: number, token: string): Promise<{ gpu: number; context: number; estimate: MemoryEstimate | null; known: boolean }>;
  voice_cancel(): Promise<CommandResult>;
  voice_delete(kind: VoiceKind, modelId: string): Promise<{ ok: boolean; error?: string; freed?: number }>;
  delete_model(name: string): Promise<{ ok: boolean; error?: string; freed?: number }>;
  disk_usage(): Promise<DiskUsage>;
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

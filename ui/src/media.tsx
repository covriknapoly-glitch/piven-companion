import { useEffect, useState, type ReactNode } from "react";
import type { AudioProvider, MediaChoice, MediaSelection, VisualProvider, WebApi } from "./bridge";
import { Dropdown, Button, Field } from "./ui";

export function VisualMediaField({ api, image, video, error, save, integrations }: {
  api: WebApi; image: MediaSelection | null; video: MediaSelection | null; error?: string;
  save: (patch: Record<string, unknown>) => Promise<unknown>; integrations: () => void;
}) {
  const [providers, setProviders] = useState<VisualProvider[] | null>(null);
  const [provider, setProvider] = useState(image?.provider ?? video?.provider);
  const [imageModel, setImage] = useState(image?.model ?? "");
  const [videoModel, setVideo] = useState(video?.model ?? "");
  const [saving, setSaving] = useState(false);
  const [loadError, setLoadError] = useState(false);
  useEffect(() => {
    let active = true;
    void api.visual_providers().then(rows => { if (active) setProviders(rows); })
      .catch(() => { if (active) setLoadError(true); });
    return () => { active = false; };
  }, [api]);

  const selected = providers?.find(row => row.id === provider);
  const imageValue = selected?.image.some(model => model.id === imageModel) ? imageModel : selected?.image[0]?.id ?? "";
  const videoValue = selected?.video.some(model => model.id === videoModel) ? videoModel : selected?.video[0]?.id ?? "";
  const dirty = provider !== (image?.provider ?? video?.provider) ||
    imageValue !== (image?.model ?? "") || videoValue !== (video?.model ?? "");
  return <Field label="Провайдер" error={error || (loadError ? "Не удалось загрузить список провайдеров." : undefined)}><div className="media-settings">
    {!providers && !loadError && <small>Обновляю список моделей…</small>}
    {!!providers?.length && <Dropdown label="Провайдер" placeholder="Выбрать провайдера" value={selected?.id ?? ""} disabled={saving}
      options={providers.map(row => ({ value: row.id, label: row.title }))}
      onChange={next => { setProvider(next); setImage(""); setVideo(""); }} />}
    {providers?.length === 0 && <small>Подключи провайдера картинок и видео в разделе «Интеграции».</small>}
    {selected?.accountError && <small className="error-text">{`Не удалось проверить аккаунт Runway: ${selected.accountError}`}</small>}
    {selected?.credits !== undefined && <small>{`Баланс Runway API · ${selected.credits} кредитов`}</small>}
    {selected?.catalogFallback && <small>Показан резервный список моделей.</small>}
    {selected && !selected.image.length && !selected.video.length && <small>Нет доступных моделей для картинок и видео.</small>}
    {!!selected?.image.length && <div className="media-choice"><span>Модель для картинок</span>
      <Dropdown label="Модель для картинок" value={imageValue} disabled={saving} onChange={setImage}
        options={selected.image.map(model => ({ value: model.id, label: model.title }))} />
    </div>}
    {!!selected?.video.length && <div className="media-choice"><span>Модель для видео</span>
      <Dropdown label="Модель для видео" value={videoValue} disabled={saving} onChange={setVideo}
        options={selected.video.map(model => ({ value: model.id, label: model.title }))} />
    </div>}
    <button type="button" className="link-btn" onClick={integrations}>Настроить подключение</button>
    {selected && <Button disabled={saving || !dirty || (!imageValue && !videoValue)} onClick={() => {
      setSaving(true);
      void save({ visualMedia: { provider, imageModel: imageValue, videoModel: videoValue } }).finally(() => setSaving(false));
    }}>Применить</Button>}
  </div></Field>;
}

const HINT = {
  ttsMedia: "Текст для озвучки отправляется выбранному сервису.",
  asrMedia: "Записанные фразы из диктовки и звонков отправляются выбранному сервису.",
};

export function MediaField({ api, providers, setting, title, current, error, save, integrations, children }: {
  api: WebApi; providers: AudioProvider[] | null; setting: "ttsMedia" | "asrMedia"; title: string;
  current: MediaSelection | null; error?: string;
  save: (value: MediaSelection | null) => Promise<unknown>; integrations: () => void; children?: ReactNode;
}) {
  const [source, setSource] = useState<"local" | MediaSelection["provider"]>(current?.provider ?? "local");
  const [model, setModel] = useState(current?.model ?? "");
  const [voice, setVoice] = useState(current?.voice ?? "");
  const [voiceList, setVoiceList] = useState<{ key: string; choices: MediaChoice[]; error?: string }>();
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setSource(current?.provider ?? "local");
    setModel(current?.model ?? "");
    setVoice(current?.voice ?? "");
  }, [current?.provider, current?.model, current?.voice]);

  const speech = setting === "ttsMedia";
  const kind = speech ? "tts" : "asr";
  const available = providers?.filter(provider => provider[kind] !== undefined);
  const selected = available?.find(provider => provider.id === source);
  const models = selected?.[kind] ?? [];
  const voiceKey = speech && selected && source !== "custom" && model ? source + ":" + model : "";
  useEffect(() => {
    if (!voiceKey) return;
    let active = true;
    void api.audio_voices(source, model).then(result => {
      if (active) setVoiceList({ key: voiceKey, choices: result.voices, error: result.error });
    }).catch(() => {
      if (active) setVoiceList({ key: voiceKey, choices: [], error: "Не удалось загрузить список голосов." });
    });
    return () => { active = false; };
  }, [api, voiceKey, source, model]);

  const remoteVoices = voiceList?.key === voiceKey ? voiceList : undefined;
  const voices = remoteVoices?.choices ?? [];
  const effectiveVoice = source === "custom" ? voice.trim() : voices.find(item => item.id === voice)?.id ?? voices[0]?.id ?? "";
  const dirty = source !== (current?.provider ?? "local") || (source !== "local" &&
    (model.trim() !== current?.model || (speech && effectiveVoice !== current?.voice)));
  return <Field label={title} error={error}>
    <div className="media-settings">
      <Dropdown label={title} value={source} disabled={saving}
        options={[
          { value: "local" as const, label: "Локальная модель" },
          ...(available ?? []).map(provider => ({ value: provider.id, label: provider.title })),
        ]} onChange={next => {
          const options = available?.find(provider => provider.id === next)?.[kind];
          setSource(next);
          setModel(next === current?.provider ? current.model : options?.[0]?.id ?? "");
          setVoice(next === current?.provider ? current.voice ?? "" : "");
        }} />
      {source === "local" && children}
      {providers && source !== "local" && !selected && <small>Выбранный провайдер отключён.</small>}
      {selected && <>
        <div className="media-choice"><span>Модель</span>
          {source !== "custom" ? <Dropdown label="Модель" value={model} disabled={saving}
            options={models.map(item => ({ value: item.id, label: item.title }))}
            onChange={id => { setModel(id); setVoice(""); }} />
          : <input className="input mono" aria-label="Идентификатор модели" value={model} disabled={saving}
              onChange={event => setModel(event.target.value)} />}
        </div>
        {speech && <div className="media-choice"><span>Голос</span>
          {source === "custom" ? <input className="input mono" aria-label="Идентификатор голоса" value={voice} disabled={saving}
            onChange={event => setVoice(event.target.value)} />
          : <Dropdown label="Голос" value={effectiveVoice} disabled={saving}
            placeholder={remoteVoices ? "Нет доступных голосов" : "Загружаю список голосов…"}
            options={voices.map(item => ({ value: item.id, label: item.title }))} onChange={setVoice} />}
        </div>}
        {remoteVoices?.error && <small className="error-text">{remoteVoices.error}</small>}
        <small>{HINT[setting]} {"Запросы могут тарифицироваться провайдером."}</small>
      </>}
      <button type="button" className="link-btn" onClick={integrations}>Настроить подключение</button>
      {dirty && <Button disabled={saving || (source !== "local" && (!selected || !model.trim() || (speech && !effectiveVoice)))}
        onClick={() => {
          setSaving(true);
          void save(source === "local" ? null : { provider: source, model: model.trim(), ...(speech && { voice: effectiveVoice }) })
            .finally(() => setSaving(false));
        }}>Применить</Button>}
    </div>
  </Field>;
}

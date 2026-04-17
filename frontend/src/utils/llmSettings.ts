export type DefaultAiModel = 'deepseek' | 'gpt4' | 'qwen'

export type LlmSettings = {
  autoGenerate: boolean
  defaultModel: DefaultAiModel
  apiKey: string
  qwenModel: string
}

export type LlmRuntimeConfig = {
  provider: 'dashscope'
  apiKey: string
  model: string
}

const STORAGE_KEY = 'education-system:llm-settings:v1'
const DEFAULT_QWEN_MODEL = 'qwen3.5-plus'

const DEFAULT_SETTINGS: LlmSettings = {
  autoGenerate: true,
  defaultModel: 'qwen',
  apiKey: '',
  qwenModel: DEFAULT_QWEN_MODEL,
}

function normalizeModel(value: unknown): DefaultAiModel {
  if (value === 'deepseek' || value === 'gpt4' || value === 'qwen') {
    return value
  }
  return DEFAULT_SETTINGS.defaultModel
}

export function getDefaultLlmSettings(): LlmSettings {
  return { ...DEFAULT_SETTINGS }
}

export function loadLlmSettings(): LlmSettings {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return getDefaultLlmSettings()
    const parsed = JSON.parse(raw) as Partial<LlmSettings>
    return {
      autoGenerate: typeof parsed.autoGenerate === 'boolean' ? parsed.autoGenerate : DEFAULT_SETTINGS.autoGenerate,
      defaultModel: normalizeModel(parsed.defaultModel),
      apiKey: typeof parsed.apiKey === 'string' ? parsed.apiKey : DEFAULT_SETTINGS.apiKey,
      qwenModel: typeof parsed.qwenModel === 'string' && parsed.qwenModel.trim() ? parsed.qwenModel.trim() : DEFAULT_QWEN_MODEL,
    }
  } catch {
    return getDefaultLlmSettings()
  }
}

export function saveLlmSettings(settings: LlmSettings) {
  const normalized: LlmSettings = {
    autoGenerate: settings.autoGenerate,
    defaultModel: normalizeModel(settings.defaultModel),
    apiKey: settings.apiKey ?? '',
    qwenModel: settings.qwenModel?.trim() || DEFAULT_QWEN_MODEL,
  }
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized))
}

export function getRuntimeLlmConfig(settings?: LlmSettings): LlmRuntimeConfig | undefined {
  const source = settings ?? loadLlmSettings()
  if (source.defaultModel !== 'qwen') return undefined
  const apiKey = source.apiKey.trim()
  if (!apiKey) return undefined
  return {
    provider: 'dashscope',
    apiKey,
    model: source.qwenModel?.trim() || DEFAULT_QWEN_MODEL,
  }
}

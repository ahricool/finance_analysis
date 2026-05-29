import type { SystemConfigDocLink } from '../types/systemConfig';

export interface SettingsHelpContent {
  title: string;
  summary?: string;
  usage?: string;
  valueNotes?: string[];
  impact?: string[];
  notes?: string[];
  docs?: SystemConfigDocLink[];
}

type SettingsHelpMap = Record<string, SettingsHelpContent>;

const settingsHelpZhCN: SettingsHelpMap = {
  'settings.ai_model.LITELLM_MODEL': {
    title: '主模型',
    summary: '指定普通分析流程默认使用的 LLM 模型。',
    usage: '推荐使用 provider/model 格式，例如 deepseek/deepseek-v4-flash、gemini/gemini-3.1-pro-preview 或 ollama/qwen3:8b。',
    valueNotes: [
      '系统配置优先级为 LITELLM_CONFIG > LLM_CHANNELS > legacy provider keys。',
      '如果留空，系统会尝试根据已配置的 API Key 或渠道声明自动推断。',
      'Agent 可通过 AGENT_LITELLM_MODEL 单独指定模型；留空时继承主模型。',
    ],
    impact: [
      '影响普通个股分析、大盘复盘、报告生成，以及未单独覆盖模型的 Agent 调用。',
    ],
    notes: [
      '无 provider 前缀时，LiteLLM 可能无法判断应该使用哪组 API Key。',
      'Ollama 本地模型应配合 OLLAMA_API_BASE 或 Ollama 渠道使用，不要误用 OPENAI_BASE_URL。',
    ],
  },
  'settings.ai_model.LLM_CHANNELS': {
    title: 'LLM 渠道列表',
    summary: '声明多个模型渠道，用于多 provider、多 Key、备用模型和可视化渠道管理。',
    usage: '填写逗号分隔的渠道名，例如 deepseek,aihubmix；每个渠道再配置 LLM_<NAME>_BASE_URL、LLM_<NAME>_API_KEY(S)、LLM_<NAME>_MODELS 等字段。',
    valueNotes: [
      '启用渠道模式后，同层运行时优先读取渠道配置。',
      '在 Docker 或 GitHub Actions 中显式注入的环境变量会覆盖 Web 设置页写入的 .env。',
      '渠道编辑器保存时只更新本次提交的 key，不会静默迁移整个旧配置。',
    ],
    impact: [
      '影响主模型、Agent 模型、fallback 模型和 Vision 模型的可选来源。',
    ],
    notes: [
      '不要把极简 legacy key 和 Channels 混用后期待两边同时生效。',
      '自定义渠道名在 GitHub Actions 中通常还需要 workflow 显式映射对应环境变量。',
    ],
  },
  'settings.notification.CUSTOM_WEBHOOK_URLS': {
    title: '自定义 Webhook',
    summary: '配置任意支持 POST JSON 的通知端点，可用于 Bark、Discord、Slack 或自建服务。',
    usage: '多个 URL 使用英文逗号分隔。Bark 可直接填写 https://api.day.app/YOUR_BARK_KEY。',
    valueNotes: [
      '未配置 CUSTOM_WEBHOOK_BODY_TEMPLATE 时，系统会按 URL 类型自动生成常见 payload。',
      '配置全局 Body 模板后，会覆盖 Bark 等自动 payload。',
      '需要认证的通用 webhook 可搭配 CUSTOM_WEBHOOK_BEARER_TOKEN。',
    ],
    impact: [
      '影响 custom 通知渠道；单个 URL 失败不会阻断其他 URL 或主分析流程。',
    ],
    notes: [
      'Bark 仍作为 custom webhook 使用，不需要新增 BARK_* 配置。',
      '自签名内网端点可评估 WEBHOOK_VERIFY_SSL=false，但不要用于公网链路。',
    ],
  },
  'settings.system.WEBUI_HOST': {
    title: 'WebUI 监听地址',
    summary: '控制 WebUI 服务绑定在哪个网络地址上。',
    usage: '本机访问通常使用 127.0.0.1；云服务器、Docker 或需要外部访问时通常使用 0.0.0.0。',
    valueNotes: [
      '.env 里的 WEBUI_HOST 在进程启动读取时优先级高于命令行 --host 参数。',
      '在设置页保存后，只会写入 .env 并重载运行时配置对象，不会让当前 WebUI/API 进程重新绑定监听地址。',
      'Docker Compose 中通常会在容器内使用 0.0.0.0，宿主机访问还取决于端口映射。',
    ],
    impact: [
      '影响重启后浏览器能否从本机、局域网或公网访问 WebUI。',
    ],
    notes: [
      '修改 WEBUI_HOST 后需要重启当前进程、Docker 容器或服务管理器才会生效。',
      '直连公网时建议同时启用 ADMIN_AUTH_ENABLED。',
      '如果部署在反向代理后面，登录限流与真实 IP 识别还需要评估 TRUST_X_FORWARDED_FOR。',
    ],
  },
};

const settingsHelpEnUS: SettingsHelpMap = {
  'settings.ai_model.LITELLM_MODEL': {
    title: 'Primary Model',
    summary: 'Selects the default LLM model for regular analysis flows.',
    usage: 'Use provider/model format, such as deepseek/deepseek-v4-flash, gemini/gemini-3.1-pro-preview, or ollama/qwen3:8b.',
    valueNotes: [
      'Runtime priority is LITELLM_CONFIG > LLM_CHANNELS > legacy provider keys.',
      'When empty, the system tries to infer a model from available API keys or channels.',
      'Agent can use AGENT_LITELLM_MODEL; when empty, it inherits the primary model.',
    ],
    impact: ['Affects regular stock analysis, market review, report generation, and Agent calls without a dedicated model.'],
    notes: [
      'Without a provider prefix, LiteLLM may not know which API key to use.',
      'For Ollama, use OLLAMA_API_BASE or an Ollama channel instead of OPENAI_BASE_URL.',
    ],
  },
  'settings.ai_model.LLM_CHANNELS': {
    title: 'LLM Channels',
    summary: 'Declares model channels for multiple providers, keys, fallbacks, and visual channel management.',
    usage: 'Use comma-separated names such as deepseek,aihubmix; then configure LLM_<NAME>_BASE_URL, LLM_<NAME>_API_KEY(S), and LLM_<NAME>_MODELS for each channel.',
    valueNotes: [
      'Once channel mode is active, runtime selection reads channel configuration first.',
      'Environment variables injected by Docker or GitHub Actions can override values saved from the Web settings page.',
      'Saving in the channel editor updates submitted keys only and does not silently migrate all old config.',
    ],
    impact: ['Affects available sources for primary, Agent, fallback, and Vision models.'],
    notes: [
      'Do not expect legacy keys and Channels to be active at the same time.',
      'Custom channel names in GitHub Actions usually need explicit workflow env mappings.',
    ],
  },
  'settings.notification.CUSTOM_WEBHOOK_URLS': {
    title: 'Custom Webhook',
    summary: 'Sends notifications to any endpoint that accepts POST JSON, such as Bark, Discord, Slack, or a self-hosted service.',
    usage: 'Separate multiple URLs with commas. For Bark, use https://api.day.app/YOUR_BARK_KEY.',
    valueNotes: [
      'Without CUSTOM_WEBHOOK_BODY_TEMPLATE, the sender auto-builds payloads for known URL types.',
      'A global body template overrides auto-detected payloads for Bark and similar URLs.',
      'Use CUSTOM_WEBHOOK_BEARER_TOKEN for generic webhook endpoints that require bearer auth.',
    ],
    impact: [
      'Affects the custom notification channel only; one URL failure does not block other URLs or the analysis flow.',
    ],
    notes: [
      'Bark stays on the custom webhook baseline and does not use BARK_* settings.',
      'Only consider WEBHOOK_VERIFY_SSL=false for trusted internal self-signed endpoints, not public routes.',
    ],
  },
  'settings.system.WEBUI_HOST': {
    title: 'WebUI Host',
    summary: 'Controls the network address the WebUI service binds to.',
    usage: 'Use 127.0.0.1 for local-only access. Use 0.0.0.0 for cloud, Docker, or external access.',
    valueNotes: [
      'WEBUI_HOST in .env has higher priority than the --host command-line argument when the process starts.',
      'Saving it from the settings page writes .env and reloads runtime config objects, but the running WebUI/API process will not rebind its host.',
      'Docker Compose commonly binds 0.0.0.0 inside the container; host access also depends on port mapping.',
    ],
    impact: ['Affects whether the WebUI can be reached locally, on the LAN, or from the public internet after restart.'],
    notes: [
      'Restart the process, Docker container, or service manager after changing WEBUI_HOST.',
      'Enable ADMIN_AUTH_ENABLED when exposing the service publicly.',
      'Behind a reverse proxy, also evaluate TRUST_X_FORWARDED_FOR for login rate limiting and real IP detection.',
    ],
  },
};

function getPreferredHelpMap(locale?: string | null): SettingsHelpMap {
  if (locale?.toLowerCase().startsWith('en')) {
    return settingsHelpEnUS;
  }
  return settingsHelpZhCN;
}

export function getSettingsHelpContent(
  helpKey?: string | null,
  fallbackDescription?: string,
  locale?: string | null,
): SettingsHelpContent | null {
  if (!helpKey) {
    return null;
  }

  const localized = getPreferredHelpMap(locale)[helpKey] ?? settingsHelpZhCN[helpKey];
  if (localized) {
    return localized;
  }

  if (fallbackDescription) {
    return {
      title: '配置说明',
      summary: fallbackDescription,
    };
  }

  return null;
}

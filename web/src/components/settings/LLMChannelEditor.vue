<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { systemConfigApi } from '@/api/systemConfig';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Badge from '@/components/common/Badge.vue';
import Button from '@/components/common/Button.vue';
import InlineAlert from '@/components/common/InlineAlert.vue';
import Select from '@/components/common/Select.vue';
import LLMChannelRow from '@/components/settings/LLMChannelRow.vue';
import {
  buildLlmFailureText,
  buildLlmTestHint,
  channelsAreEqual,
  channelsToUpdateItems,
  getFirstCapabilityHint,
  getLlmTroubleshootingHint,
  isRuntimeModelAvailable,
  normalizeAgentPrimaryModel,
  parseChannelsFromItems,
  parseRuntimeConfigFromItems,
  resolveModelPreview,
  runtimeConfigsAreEqual,
  sanitizeRuntimeConfigForSave,
  splitModels,
  summarizeCapabilityResults,
  type ChannelConfig,
  type RuntimeConfig,
  type ChannelCapabilityState,
  type ChannelDiscoveryState,
  type ChannelTestState,
} from '@/components/settings/llmChannelEditorCore';
import { LLM_PROVIDER_TEMPLATES, getProviderTemplate } from '@/components/settings/llmProviderTemplates';
import type { LLMCapabilityCheck } from '@/types/systemConfig';
import { computed, ref, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    items: Array<{ key: string; value: string }>;
    configVersion: string;
    maskToken: string;
    disabled?: boolean;
  }>(),
  { disabled: false },
);

const emit = defineEmits<{
  saved: [updatedItems: Array<{ key: string; value: string }>];
}>();

const initialChannels = computed(() => parseChannelsFromItems(props.items));
const initialNames = computed(() => initialChannels.value.map((channel) => channel.name));
const initialRuntimeConfig = computed(() => parseRuntimeConfigFromItems(props.items));
const savedItemMap = computed(() => new Map(props.items.map((item) => [item.key.toUpperCase(), item.value])));
const hasLitellmConfig = computed(
  () => props.items.some((item) => item.key === 'LITELLM_CONFIG' && item.value.trim().length > 0),
);
const managesRuntimeConfig = computed(() => !hasLitellmConfig.value);

const channelsFingerprint = computed(() => JSON.stringify(initialChannels.value));
const runtimeFingerprint = computed(() => JSON.stringify(initialRuntimeConfig.value));

const channels = ref<ChannelConfig[]>([...initialChannels.value]);
const runtimeConfig = ref<RuntimeConfig>({ ...initialRuntimeConfig.value });
const isSaving = ref(false);
const saveMessage = ref<
  | { type: 'success'; text: string }
  | { type: 'error'; error: ParsedApiError }
  | { type: 'local-error'; text: string }
  | null
>(null);
const saveWarnings = ref<string[]>([]);
const visibleKeys = ref<Record<number, boolean>>({});
const testStates = ref<Record<number, ChannelTestState>>({});
const discoveryStates = ref<Record<string, ChannelDiscoveryState>>({});
const capabilityStates = ref<Record<string, ChannelCapabilityState>>({});
const expandedRows = ref<Record<number, boolean>>({});
const isCollapsed = ref(false);
const addPreset = ref('aihubmix');
const addChannelIdRef = ref(0);

const prevChannelsRef = ref(channelsFingerprint.value);
const prevRuntimeRef = ref(runtimeFingerprint.value);
const pendingSaveFeedbackFingerprintRef = ref<{ channels: string; runtime: string } | null>(null);
const discoveryNonceRef = ref<Record<string, number>>({});
const discoveryRequestIdRef = ref(0);
const capabilityNonceRef = ref<Record<string, number>>({});
const capabilityRequestIdRef = ref(0);

watch(
  [channelsFingerprint, runtimeFingerprint, initialChannels, initialRuntimeConfig],
  ([cf, rf, initCh, initRt]) => {
    if (prevChannelsRef.value === cf && prevRuntimeRef.value === rf) {
      return;
    }
    prevChannelsRef.value = cf;
    prevRuntimeRef.value = rf;
    const pendingSaveFeedbackFingerprint = pendingSaveFeedbackFingerprintRef.value;
    const preserveSaveFeedback =
      pendingSaveFeedbackFingerprint?.channels === cf && pendingSaveFeedbackFingerprint.runtime === rf;
    pendingSaveFeedbackFingerprintRef.value = null;
    channels.value = [...initCh];
    runtimeConfig.value = { ...initRt };
    visibleKeys.value = {};
    testStates.value = {};
    discoveryStates.value = {};
    capabilityStates.value = {};
    expandedRows.value = {};
    discoveryNonceRef.value = {};
    capabilityNonceRef.value = {};
    if (!preserveSaveFeedback) {
      saveMessage.value = null;
      saveWarnings.value = [];
    }
    isCollapsed.value = false;
  },
);

const availableModels = computed(() => {
  if (!managesRuntimeConfig.value) {
    return [];
  }
  const seen = new Set<string>();
  const models: string[] = [];
  for (const channel of channels.value) {
    if (!channel.enabled || !channel.name.trim()) {
      continue;
    }
    for (const model of resolveModelPreview(channel.models, channel.protocol)) {
      if (!model || seen.has(model)) {
        continue;
      }
      seen.add(model);
      models.push(model);
    }
  }
  return models;
});

const hasChanges = computed(() => {
  const rt = runtimeConfig.value;
  const initRt = initialRuntimeConfig.value;
  const runtimeChanged =
    rt.primaryModel !== initRt.primaryModel
    || rt.agentPrimaryModel !== initRt.agentPrimaryModel
    || rt.visionModel !== initRt.visionModel
    || rt.temperature !== initRt.temperature
    || rt.fallbackModels.join(',') !== initRt.fallbackModels.join(',');

  if (runtimeChanged || channels.value.length !== initialChannels.value.length) {
    return true;
  }
  return channels.value.some((channel, index) => !channelsAreEqual(channel, initialChannels.value[index]));
});

const busy = computed(() => props.disabled || isSaving.value);

function buildModelOptions(models: string[], selectedModel: string, autoLabel: string) {
  const options: Array<{ value: string; label: string }> = [{ value: '', label: autoLabel }];
  if (selectedModel && !models.includes(selectedModel)) {
    options.push({ value: selectedModel, label: `${selectedModel}（当前配置）` });
  }
  for (const model of models) {
    options.push({ value: model, label: model });
  }
  return options;
}

function updateChannel(index: number, field: keyof ChannelConfig, value: string | boolean) {
  const currentChannel = channels.value[index];
  channels.value = channels.value.map((channel, rowIndex) => {
    if (rowIndex !== index) return channel;
    const updated = { ...channel, [field]: value } as ChannelConfig;
    if (field === 'name' && typeof value === 'string') {
      const newPreset = getProviderTemplate(value);
      if (newPreset) {
        const oldPreset = getProviderTemplate(channel.name);
        if (!updated.baseUrl || updated.baseUrl === (oldPreset?.baseUrl ?? '')) {
          updated.baseUrl = newPreset.baseUrl;
        }
        updated.protocol = newPreset.protocol;
        if (!updated.models || updated.models === (oldPreset?.placeholderModels ?? '')) {
          updated.models = newPreset.placeholderModels;
        }
      }
    }
    return updated;
  });

  const ts = { ...testStates.value };
  if (index in ts) delete ts[index];
  testStates.value = ts;

  if (field !== 'models' && field !== 'enabled') {
    const ch = channels.value[index];
    const ds = { ...discoveryStates.value };
    if (ch && ch.id in ds) {
      delete ds[ch.id];
      delete discoveryNonceRef.value[ch.id];
      discoveryStates.value = ds;
    }
  }
  if (currentChannel) {
    delete capabilityNonceRef.value[currentChannel.id];
    const prevCap = capabilityStates.value[currentChannel.id];
    if (prevCap) {
      capabilityStates.value = {
        ...capabilityStates.value,
        [currentChannel.id]: {
          ...prevCap,
          status: 'idle',
          text: undefined,
          hint: undefined,
          results: {},
        },
      };
    }
  }
}

function removeChannel(index: number) {
  const removedChannelId = channels.value[index]?.id || '';
  channels.value = channels.value.filter((_, rowIndex) => rowIndex !== index);
  visibleKeys.value = {};
  testStates.value = {};
  if (removedChannelId) {
    const ds = { ...discoveryStates.value };
    delete ds[removedChannelId];
    discoveryStates.value = ds;
    const cs = { ...capabilityStates.value };
    delete cs[removedChannelId];
    capabilityStates.value = cs;
    const nn = { ...discoveryNonceRef.value };
    delete nn[removedChannelId];
    discoveryNonceRef.value = nn;
    delete capabilityNonceRef.value[removedChannelId];
  }
  expandedRows.value = {};
}

function addChannel() {
  const preset = getProviderTemplate(addPreset.value) || getProviderTemplate('custom');
  if (!preset) return;
  const existingNames = new Set(channels.value.map((c) => c.name));
  const baseName = addPreset.value === 'custom' ? 'custom' : addPreset.value;
  let nextName = baseName;
  let counter = 2;
  while (existingNames.has(nextName)) {
    nextName = `${baseName}${counter}`;
    counter += 1;
  }
  addChannelIdRef.value += 1;
  channels.value = [
    ...channels.value,
    {
      id: `added:${addChannelIdRef.value}`,
      name: nextName,
      protocol: preset.protocol,
      baseUrl: preset.baseUrl,
      apiKey: '',
      models: preset.placeholderModels || '',
      enabled: true,
    },
  ];
  testStates.value = {};
  discoveryStates.value = {};
  capabilityStates.value = {};
  discoveryNonceRef.value = {};
  capabilityNonceRef.value = {};
  expandedRows.value = { ...expandedRows.value, [channels.value.length - 1]: true };
  isCollapsed.value = false;
}

async function handleSave() {
  const hasEmptyName = channels.value.some((c) => !c.name.trim());
  if (hasEmptyName) {
    saveMessage.value = { type: 'local-error', text: '渠道名称不能为空，且只能包含字母、数字或下划线。' };
    return;
  }

  const runtimeConfigForSave = managesRuntimeConfig.value
    ? sanitizeRuntimeConfigForSave(runtimeConfig.value, availableModels.value, savedItemMap.value)
    : runtimeConfig.value;
  if (!runtimeConfigsAreEqual(runtimeConfigForSave, runtimeConfig.value)) {
    runtimeConfig.value = runtimeConfigForSave;
  }

  if (managesRuntimeConfig.value) {
    if (
      runtimeConfigForSave.primaryModel
      && !isRuntimeModelAvailable(runtimeConfigForSave.primaryModel, availableModels.value, savedItemMap.value)
    ) {
      saveMessage.value = {
        type: 'local-error',
        text: '当前主模型不在已启用渠道的模型列表中，请重新选择。',
      };
      return;
    }
    if (
      runtimeConfigForSave.agentPrimaryModel
      && !isRuntimeModelAvailable(
        runtimeConfigForSave.agentPrimaryModel,
        availableModels.value,
        savedItemMap.value,
      )
    ) {
      saveMessage.value = {
        type: 'local-error',
        text: '当前 Agent 主模型不在已启用渠道的模型列表中，请重新选择。',
      };
      return;
    }
    if (
      runtimeConfigForSave.fallbackModels.some(
        (model) => !isRuntimeModelAvailable(model, availableModels.value, savedItemMap.value),
      )
    ) {
      saveMessage.value = { type: 'local-error', text: '存在无效的备选模型，请重新选择。' };
      return;
    }
    if (
      runtimeConfigForSave.visionModel
      && !isRuntimeModelAvailable(
        runtimeConfigForSave.visionModel,
        availableModels.value,
        savedItemMap.value,
      )
    ) {
      saveMessage.value = {
        type: 'local-error',
        text: '当前 Vision 模型不在已启用渠道的模型列表中，请重新选择。',
      };
      return;
    }
  }

  isSaving.value = true;
  saveMessage.value = null;
  saveWarnings.value = [];
  try {
    const updateItems = channelsToUpdateItems(
      channels.value,
      initialNames.value,
      runtimeConfigForSave,
      managesRuntimeConfig.value,
    );
    const response = await systemConfigApi.update({
      configVersion: props.configVersion,
      maskToken: props.maskToken,
      reloadNow: true,
      items: updateItems,
    });
    const responseWarnings = response.warnings || [];
    emit('saved', updateItems);
    pendingSaveFeedbackFingerprintRef.value = {
      channels: JSON.stringify(parseChannelsFromItems(updateItems)),
      runtime: JSON.stringify(parseRuntimeConfigFromItems(updateItems)),
    };
    saveWarnings.value = responseWarnings;
    saveMessage.value = {
      type: 'success',
      text: managesRuntimeConfig.value ? 'AI 配置已保存' : '渠道配置已保存',
    };
  } catch (error: unknown) {
    saveWarnings.value = [];
    saveMessage.value = { type: 'error', error: getParsedApiError(error) };
  } finally {
    isSaving.value = false;
  }
}

async function handleTest(channel: ChannelConfig, index: number) {
  testStates.value = { ...testStates.value, [index]: { status: 'loading', text: '测试中...' } };
  try {
    const result = await systemConfigApi.testLLMChannel({
      name: channel.name,
      protocol: channel.protocol,
      baseUrl: channel.baseUrl,
      apiKey: channel.apiKey,
      models: splitModels(channel.models),
      enabled: channel.enabled,
    });
    const text = result.success
      ? `连接成功${result.resolvedModel ? ` · ${result.resolvedModel}` : ''}${result.latencyMs ? ` · ${result.latencyMs} ms` : ''}`
      : buildLlmFailureText(result);
    const hint = result.success ? undefined : buildLlmTestHint(result);
    testStates.value = {
      ...testStates.value,
      [index]: { status: result.success ? 'success' : 'error', text, hint },
    };
  } catch (error: unknown) {
    const parsed = getParsedApiError(error);
    testStates.value = { ...testStates.value, [index]: { status: 'error', text: parsed.message || '测试失败' } };
  }
}

async function handleDiscoverModels(channel: ChannelConfig) {
  const requestId = discoveryRequestIdRef.value + 1;
  discoveryRequestIdRef.value = requestId;
  discoveryNonceRef.value[channel.id] = requestId;
  const nonce = requestId;

  discoveryStates.value = {
    ...discoveryStates.value,
    [channel.id]: {
      status: 'loading',
      text: '正在获取模型列表...',
      hint: undefined,
      models: discoveryStates.value[channel.id]?.models || [],
    },
  };
  try {
    const result = await systemConfigApi.discoverLLMChannelModels({
      name: channel.name,
      protocol: channel.protocol,
      baseUrl: channel.baseUrl,
      apiKey: channel.apiKey,
      models: splitModels(channel.models),
    });
    if (discoveryNonceRef.value[channel.id] !== nonce) return;
    discoveryStates.value = {
      ...discoveryStates.value,
      [channel.id]: {
        status: result.success ? 'success' : 'error',
        text: result.success
          ? `已获取 ${result.models.length} 个模型${result.latencyMs ? ` · ${result.latencyMs} ms` : ''}`
          : buildLlmFailureText(result),
        hint: result.success
          ? undefined
          : getLlmTroubleshootingHint(result.errorCode, result.stage, 'discovery', result.details),
        models: result.success ? result.models : (discoveryStates.value[channel.id]?.models || []),
      },
    };
  } catch (error: unknown) {
    if (discoveryNonceRef.value[channel.id] !== nonce) return;
    const parsed = getParsedApiError(error);
    discoveryStates.value = {
      ...discoveryStates.value,
      [channel.id]: {
        status: 'error',
        text: parsed.message || '获取模型失败',
        hint: undefined,
        models: discoveryStates.value[channel.id]?.models || [],
      },
    };
  }
}

function toggleCapability(channel: ChannelConfig, capability: LLMCapabilityCheck) {
  const previous = capabilityStates.value[channel.id] || { selected: [], status: 'idle' as const, results: {} };
  const selected = previous.selected.includes(capability)
    ? previous.selected.filter((item) => item !== capability)
    : [...previous.selected, capability];
  capabilityStates.value = {
    ...capabilityStates.value,
    [channel.id]: {
      ...previous,
      selected,
      status: previous.status === 'loading' ? previous.status : 'idle',
      text: previous.status === 'loading' ? previous.text : undefined,
      hint: previous.status === 'loading' ? previous.hint : undefined,
      results: previous.status === 'loading' ? previous.results : {},
    },
  };
}

async function handleCapabilityCheck(channel: ChannelConfig) {
  const selected = capabilityStates.value[channel.id]?.selected || [];
  if (selected.length === 0) return;

  const requestId = capabilityRequestIdRef.value + 1;
  capabilityRequestIdRef.value = requestId;
  capabilityNonceRef.value[channel.id] = requestId;
  const nonce = requestId;

  capabilityStates.value = {
    ...capabilityStates.value,
    [channel.id]: {
      selected,
      status: 'loading',
      text: '正在检测运行时能力...',
      hint: undefined,
      results: {},
    },
  };

  try {
    const result = await systemConfigApi.testLLMChannel({
      name: channel.name,
      protocol: channel.protocol,
      baseUrl: channel.baseUrl,
      apiKey: channel.apiKey,
      models: splitModels(channel.models),
      enabled: channel.enabled,
      capabilityChecks: selected,
    });
    if (capabilityNonceRef.value[channel.id] !== nonce) return;
    const capabilityResults = result.capabilityResults || {};
    const hasFailure = Object.values(capabilityResults).some((item) => item?.status === 'failed');
    const hasSkipped = Object.values(capabilityResults).some((item) => item?.status === 'skipped');
    capabilityStates.value = {
      ...capabilityStates.value,
      [channel.id]: {
        selected,
        status: hasFailure || hasSkipped || !result.success ? 'error' : 'success',
        text:
          Object.keys(capabilityResults).length > 0
            ? summarizeCapabilityResults(capabilityResults)
            : result.success
              ? '未返回能力检测结果'
              : buildLlmFailureText(result),
        hint:
          getFirstCapabilityHint(capabilityResults) || (!result.success ? buildLlmTestHint(result) : undefined),
        results: capabilityResults,
      },
    };
  } catch (error: unknown) {
    if (capabilityNonceRef.value[channel.id] !== nonce) return;
    const parsed = getParsedApiError(error);
    capabilityStates.value = {
      ...capabilityStates.value,
      [channel.id]: {
        selected,
        status: 'error',
        text: parsed.message || '能力检测失败',
        hint: undefined,
        results: {},
      },
    };
  }
}

function toggleKeyVisibility(index: number, nextVisible: boolean) {
  visibleKeys.value = { ...visibleKeys.value, [index]: nextVisible };
}

function toggleExpand(index: number) {
  expandedRows.value = { ...expandedRows.value, [index]: !expandedRows.value[index] };
}

function setPrimaryModel(value: string) {
  runtimeConfig.value = {
    ...runtimeConfig.value,
    primaryModel: value,
    fallbackModels: runtimeConfig.value.fallbackModels.filter((model) => model !== value),
  };
}

function toggleFallbackModel(model: string) {
  const rt = runtimeConfig.value;
  const alreadySelected = rt.fallbackModels.includes(model);
  runtimeConfig.value = {
    ...rt,
    fallbackModels: alreadySelected
      ? rt.fallbackModels.filter((item) => item !== model)
      : [...rt.fallbackModels, model],
  };
}
</script>

<template>
  <div class="space-y-4">
    <button
      type="button"
      class="flex w-full items-center justify-between rounded-[1.35rem] border border-[var(--settings-border)] bg-[var(--settings-surface)] px-5 py-4 text-left shadow-soft-card transition-[background-color,border-color,box-shadow] duration-200 hover:border-[var(--settings-border-strong)] hover:bg-[var(--settings-surface-hover)]"
      @click="isCollapsed = !isCollapsed"
    >
      <div class="space-y-1">
        <div class="flex items-center gap-2">
          <h3 class="text-base font-semibold text-foreground">AI 模型配置</h3>
          <Badge variant="info" class="settings-accent-badge">渠道管理</Badge>
        </div>
        <p class="text-xs text-muted-text">
          添加服务商渠道后可自动获取模型列表并多选，也可继续手动填写。配置会自动同步到 .env 文件。
        </p>
      </div>
      <span class="text-xs text-muted-text">{{ isCollapsed ? '▶ 展开' : '▼ 收起' }}</span>
    </button>

    <div v-if="!isCollapsed" class="space-y-4 animate-in fade-in slide-in-from-top-2 duration-300">
      <div class="rounded-[1.35rem] border border-[var(--settings-border)] bg-[var(--settings-surface)] p-4 shadow-soft-card">
        <div class="mb-3 flex items-center justify-between">
          <div>
            <h4 class="text-sm font-medium text-foreground">快速添加渠道</h4>
            <p class="mt-1 text-xs text-secondary-text">先选择预设服务商，再一键创建配置草稿。</p>
          </div>
          <Badge variant="default" class="border-[var(--settings-border)] bg-[var(--settings-surface-hover)] text-muted-text">
            {{ channels.length }} 个渠道
          </Badge>
        </div>
        <div class="flex items-center gap-2">
          <Button type="button" variant="settings-primary" class="whitespace-nowrap" :disabled="busy" @click="addChannel">
            + 添加渠道
          </Button>
          <Select
            v-model="addPreset"
            class="flex-1"
            :options="LLM_PROVIDER_TEMPLATES.map((p) => ({ value: p.channelId, label: p.label }))"
            :disabled="busy"
            placeholder="选择服务商"
          />
        </div>
      </div>

      <div class="space-y-2">
        <div class="flex items-center justify-between px-1">
          <span class="text-xs font-medium uppercase tracking-wider text-muted-text">渠道列表</span>
          <span v-if="channels.length > 0" class="text-[10px] text-muted-text">
            {{ channels.filter((c) => c.enabled).length }}/{{ channels.length }} 已启用
          </span>
        </div>

        <div
          v-if="channels.length === 0"
          class="settings-surface-overlay-muted rounded-[1.35rem] border border-dashed settings-border-strong px-4 py-10 text-center"
        >
          <p class="text-sm font-medium text-secondary-text">还没有渠道</p>
          <p class="mt-1 text-xs text-muted-text">选择服务商预设后点击“添加渠道”即可开始配置。</p>
        </div>
        <LLMChannelRow
          v-for="(channel, index) in channels"
          :key="channel.id"
          :channel="channel"
          :index="index"
          :busy="busy"
          :visible-key="Boolean(visibleKeys[index])"
          :expanded="Boolean(expandedRows[index])"
          :test-state="testStates[index]"
          :discovery-state="discoveryStates[channel.id]"
          :capability-state="capabilityStates[channel.id]"
          @update="updateChannel"
          @remove="removeChannel"
          @toggle-expand="toggleExpand"
          @toggle-key-visibility="toggleKeyVisibility"
          @test="(ch, idx) => void handleTest(ch, idx)"
          @discover-models="(ch) => void handleDiscoverModels(ch)"
          @toggle-capability="toggleCapability"
          @check-capabilities="(ch) => void handleCapabilityCheck(ch)"
        />
      </div>

      <div v-if="managesRuntimeConfig" class="rounded-[1.35rem] border border-[var(--settings-border)] bg-[var(--settings-surface)] p-4 shadow-soft-card">
        <div class="mb-4 flex items-center justify-between">
          <div>
            <span class="settings-accent-text text-xs font-medium uppercase tracking-wider">运行时参数</span>
            <p class="mt-1 text-[11px] text-muted-text">主模型、备选模型、Vision 与 Temperature 会直接写入运行时配置。</p>
          </div>
          <Badge variant="default" class="border-[var(--settings-border)] bg-[var(--settings-surface-hover)] text-muted-text">
            Runtime
          </Badge>
        </div>
        <div class="mb-4">
          <label class="mb-1 block text-xs text-muted-text">Temperature</label>
          <div class="flex items-center gap-3">
            <input
              v-model="runtimeConfig.temperature"
              type="range"
              min="0"
              max="2"
              step="0.1"
              :disabled="busy"
              class="settings-input-checkbox h-1.5 flex-1 cursor-pointer rounded-full bg-border/60"
            />
            <span class="w-8 text-right text-sm text-secondary-text">{{ runtimeConfig.temperature }}</span>
          </div>
          <p class="mt-1 text-[11px] text-secondary-text">
            控制模型输出随机性，0 为确定性输出，2 为最大随机性，推荐 0.7。
          </p>
        </div>

        <div
          v-if="availableModels.length === 0"
          class="rounded-xl border border-dashed settings-border-strong settings-surface-overlay-soft px-3 py-2 text-xs text-muted-text"
        >
          先添加至少一个已启用渠道并填写模型，下面的主模型 / 备选模型 / Vision 选项才会出现。
        </div>
        <div v-else class="space-y-4">
          <div>
            <label for="runtime-primary-model" class="mb-1 block text-xs text-muted-text">主模型</label>
            <Select
              id="runtime-primary-model"
              :model-value="runtimeConfig.primaryModel"
              :options="buildModelOptions(availableModels, runtimeConfig.primaryModel, '自动（使用第一个可用模型）')"
              :disabled="busy"
              placeholder=""
              @update:model-value="setPrimaryModel"
            />
          </div>
          <div>
            <label for="runtime-agent-primary-model" class="mb-1 block text-xs text-muted-text">Agent 主模型</label>
            <Select
              id="runtime-agent-primary-model"
              :model-value="runtimeConfig.agentPrimaryModel"
              :options="buildModelOptions(availableModels, runtimeConfig.agentPrimaryModel, '自动（继承普通分析主模型）')"
              :disabled="busy"
              placeholder=""
              @update:model-value="
                (v) => {
                  runtimeConfig.agentPrimaryModel = normalizeAgentPrimaryModel(v);
                }
              "
            />
          </div>
          <div>
            <label class="mb-2 block text-xs text-muted-text">备选模型</label>
            <div class="space-y-2 rounded-xl border settings-border-strong settings-surface-overlay-soft p-3">
              <label v-for="model in availableModels" :key="model" class="flex items-center gap-2 text-sm text-secondary-text">
                <input
                  type="checkbox"
                  :checked="runtimeConfig.fallbackModels.includes(model)"
                  :disabled="busy || model === runtimeConfig.primaryModel"
                  class="settings-input-checkbox h-4 w-4 rounded border-border/70 bg-base"
                  @change="toggleFallbackModel(model)"
                />
                <span>{{ model }}</span>
              </label>
            </div>
            <p class="mt-1 text-[11px] text-secondary-text">
              备选模型只会在主模型失败时使用。主模型不会重复加入备选模型。
            </p>
          </div>
          <div>
            <label for="runtime-vision-model" class="mb-1 block text-xs text-muted-text">Vision 模型</label>
            <Select
              id="runtime-vision-model"
              :model-value="runtimeConfig.visionModel"
              :options="buildModelOptions(availableModels, runtimeConfig.visionModel, '自动（跟随 Vision 默认逻辑）')"
              :disabled="busy"
              placeholder=""
              @update:model-value="(v) => { runtimeConfig.visionModel = v; }"
            />
          </div>
        </div>
      </div>

      <InlineAlert
        v-else
        variant="warning"
        class="rounded-[1.35rem] px-4 py-3 text-xs shadow-none"
      >
        检测到已配置高级模型路由 YAML：此处仅管理渠道条目和基础连接信息。运行时主模型 / 备选模型 / Vision / Temperature 仍由下方通用字段决定；若 YAML 解析成功，则以其中的路由与可用模型声明为准，本配置不会覆盖 YAML 文件本身。
      </InlineAlert>

      <div class="flex flex-wrap items-center gap-3">
        <Button type="button" variant="settings-primary" glow :disabled="busy || !hasChanges" @click="handleSave()">
          {{ isSaving ? '保存中...' : managesRuntimeConfig ? '保存 AI 配置' : '保存渠道配置' }}
        </Button>
        <span v-if="!hasChanges" class="text-xs text-muted-text">当前没有未保存的改动</span>
      </div>

      <InlineAlert
        v-if="saveMessage?.type === 'success'"
        variant="success"
        class="rounded-lg px-3 py-2 text-sm shadow-none"
      >
        {{ saveMessage.text }}
      </InlineAlert>

      <InlineAlert v-if="saveWarnings.length > 0" variant="warning" title="保存后提示" class="rounded-lg px-3 py-2 text-sm shadow-none">
        <div class="space-y-1">
          <p v-for="warning in saveWarnings" :key="warning">{{ warning }}</p>
        </div>
      </InlineAlert>

      <InlineAlert
        v-if="saveMessage?.type === 'local-error'"
        variant="danger"
        class="rounded-lg px-3 py-2 text-sm shadow-none"
      >
        {{ saveMessage.text }}
      </InlineAlert>

      <ApiErrorAlert v-if="saveMessage?.type === 'error'" :error="saveMessage.error" />
    </div>
  </div>
</template>

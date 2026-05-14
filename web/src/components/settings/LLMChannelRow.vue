<script setup lang="ts">
import Badge from '@/components/common/Badge.vue';
import Button from '@/components/common/Button.vue';
import Input from '@/components/common/Input.vue';
import Select from '@/components/common/Select.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import Tooltip from '@/components/common/Tooltip.vue';
import type { LLMCapabilityCheck } from '@/types/systemConfig';
import {
  CAPABILITY_STATUS_LABELS,
  LLM_PROVIDER_CAPABILITY_LABELS,
  MODEL_PLACEHOLDERS_BY_PROTOCOL,
  PROTOCOL_OPTIONS,
  RUNTIME_CAPABILITY_OPTIONS,
  areModelsEquivalent,
  getCapabilityResultVariant,
  getProviderTemplate,
  isKnownProviderTemplate,
  normalizeProtocol,
  splitModels,
  toggleModelSelection,
  type ChannelCapabilityState,
  type ChannelConfig,
  type ChannelDiscoveryState,
  type ChannelTestState,
} from '@/components/settings/llmChannelEditorCore';
import { computed } from 'vue';

const props = defineProps<{
  channel: ChannelConfig;
  index: number;
  busy: boolean;
  visibleKey: boolean;
  expanded: boolean;
  testState?: ChannelTestState;
  discoveryState?: ChannelDiscoveryState;
  capabilityState?: ChannelCapabilityState;
}>();

const emit = defineEmits<{
  update: [index: number, field: keyof ChannelConfig, value: string | boolean];
  remove: [index: number];
  toggleExpand: [index: number];
  toggleKeyVisibility: [index: number, visible: boolean];
  test: [channel: ChannelConfig, index: number];
  discoverModels: [channel: ChannelConfig];
  toggleCapability: [channel: ChannelConfig, capability: LLMCapabilityCheck];
  checkCapabilities: [channel: ChannelConfig];
}>();

const preset = computed(() => getProviderTemplate(props.channel.name));
const showProviderTemplateDetails = computed(() => isKnownProviderTemplate(props.channel.name));
const displayName = computed(() => preset.value?.label || props.channel.name);
const providerCapabilities = computed(() =>
  showProviderTemplateDetails.value ? preset.value?.capabilities || [] : [],
);
const providerSources = computed(() =>
  showProviderTemplateDetails.value ? preset.value?.officialSources || [] : [],
);
const providerHint = computed(() =>
  showProviderTemplateDetails.value ? preset.value?.configHint : undefined,
);
const selectedModels = computed(() => splitModels(props.channel.models));
const discoveredModels = computed(() => props.discoveryState?.models || []);
const manualOnlyModels = computed(() =>
  selectedModels.value.filter(
    (model) =>
      !discoveredModels.value.some((discoveredModel) =>
        areModelsEquivalent(model, discoveredModel, props.channel.protocol),
      ),
  ),
);
const modelCount = computed(() => selectedModels.value.length);
const hasKey = computed(() => props.channel.apiKey.length > 0);
const statusVariant = computed(() =>
  props.testState?.status === 'success'
    ? 'success'
    : props.testState?.status === 'error'
      ? 'danger'
      : props.testState?.status === 'loading'
        ? 'warning'
        : 'default',
);
const selectedCapabilities = computed(() => props.capabilityState?.selected || []);
const capabilityResults = computed(() => props.capabilityState?.results || {});
const capabilityBusy = computed(() => props.capabilityState?.status === 'loading');

function onHeaderKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    emit('toggleExpand', props.index);
  }
}
</script>

<template>
  <div
    class="mb-2 overflow-hidden rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface)] shadow-soft-card transition-[background-color,border-color,box-shadow] duration-200 hover:border-[var(--settings-border-strong)] hover:bg-[var(--settings-surface-hover)]"
  >
    <div
      class="flex cursor-pointer select-none items-center gap-2.5 px-4 py-3 transition-colors"
      role="button"
      tabindex="0"
      @click="emit('toggleExpand', index)"
      @keydown="onHeaderKeydown"
    >
      <span
        :class="[
          'w-4 shrink-0 text-[11px] text-muted-text transition-transform',
          expanded ? 'rotate-90' : '',
        ]"
      >
        ▶
      </span>

      <input
        type="checkbox"
        :checked="channel.enabled"
        :disabled="busy"
        class="settings-input-checkbox h-4 w-4 shrink-0 rounded border-border/70 bg-base"
        @click.stop
        @change="emit('update', index, 'enabled', ($event.target as HTMLInputElement).checked)"
      />

      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="truncate text-sm font-semibold text-foreground">{{ displayName }}</span>
          <Badge variant="info" class="hidden sm:inline-flex">{{ channel.protocol }}</Badge>
        </div>
        <p class="mt-0.5 truncate text-[11px] text-secondary-text">
          {{ modelCount > 0 ? `${modelCount} 个模型已配置` : '未配置模型' }}
        </p>
      </div>

      <span class="flex shrink-0 items-center gap-2">
        <Tooltip v-if="testState?.status === 'success'" content="连接正常">
          <span class="inline-flex">
            <StatusDot tone="success" />
          </span>
        </Tooltip>
        <Tooltip v-if="testState?.status === 'error'" content="连接失败">
          <span class="inline-flex">
            <StatusDot tone="danger" />
          </span>
        </Tooltip>
        <Tooltip v-if="testState?.status === 'loading'" content="测试中">
          <span class="inline-flex">
            <StatusDot tone="warning" pulse />
          </span>
        </Tooltip>
        <Badge v-if="!hasKey && channel.protocol !== 'ollama'" variant="warning">未填 Key</Badge>
        <Badge v-if="testState?.status !== 'idle'" :variant="statusVariant">
          {{
            testState?.status === 'success'
              ? '连接正常'
              : testState?.status === 'error'
                ? '连接失败'
                : '测试中'
          }}
        </Badge>
      </span>

      <Tooltip content="删除渠道">
        <span class="inline-flex">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            class="h-8 shrink-0 px-2 text-xs text-muted-text hover:text-rose-300"
            :disabled="busy"
            @click.stop="
              () => {
                emit('remove', index);
              }
            "
          >
            ✕
          </Button>
        </span>
      </Tooltip>
    </div>

    <div v-if="expanded" class="settings-surface-overlay-soft space-y-4 px-4 py-4">
      <div class="grid gap-2 sm:grid-cols-2">
        <Input
          label="渠道名称"
          :value="channel.name"
          :disabled="busy"
          placeholder="primary"
          @input="
            emit(
              'update',
              index,
              'name',
              ($event.target as HTMLInputElement).value.toLowerCase().replace(/[^a-z0-9_]/g, ''),
            )
          "
        />
        <div class="space-y-2">
          <label class="block text-sm font-medium text-foreground">协议</label>
          <Select
            :model-value="channel.protocol"
            :options="PROTOCOL_OPTIONS"
            :disabled="busy"
            placeholder="选择协议"
            @update:model-value="emit('update', index, 'protocol', normalizeProtocol($event))"
          />
        </div>
      </div>

      <Input
        label="Base URL"
        :value="channel.baseUrl"
        :disabled="busy"
        :placeholder="
          channel.protocol === 'gemini' || channel.protocol === 'anthropic'
            ? '官方接口可留空'
            : preset?.baseUrl || 'https://api.example.com/v1'
        "
        @input="emit('update', index, 'baseUrl', ($event.target as HTMLInputElement).value)"
      />

      <div
        v-if="showProviderTemplateDetails"
        class="space-y-2 rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface-hover)] p-3"
      >
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[11px] font-medium text-muted-text">配置参考</span>
          <Tooltip v-for="capability in providerCapabilities" :key="capability" :content="LLM_PROVIDER_CAPABILITY_LABELS[capability].hint">
            <span class="inline-flex">
              <Badge
                variant="default"
                class="border-[var(--settings-border)] bg-[var(--settings-surface)] text-secondary-text"
              >
                {{ LLM_PROVIDER_CAPABILITY_LABELS[capability].label }}
              </Badge>
            </span>
          </Tooltip>
        </div>
        <p v-if="providerHint" class="text-[11px] leading-5 text-secondary-text">{{ providerHint }}</p>
        <p v-if="providerSources.length > 0" class="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] leading-5 text-secondary-text">
          <span>官方来源：</span>
          <a
            v-for="source in providerSources"
            :key="source.url"
            :href="source.url"
            target="_blank"
            rel="noreferrer"
            class="settings-accent-text underline-offset-2 hover:underline"
          >
            {{ source.label }}
          </a>
        </p>
        <p class="text-[11px] leading-5 text-muted-text">能力标签仅用于配置参考，不代表运行时能力已验证通过。</p>
      </div>

      <Input
        label="API Key"
        type="password"
        allow-toggle-password
        icon-type="key"
        :password-visible="visibleKey"
        :value="channel.apiKey"
        :disabled="busy"
        :placeholder="channel.protocol === 'ollama' ? '本地 Ollama 可留空' : '支持多个 Key 逗号分隔'"
        @update:password-visible="emit('toggleKeyVisibility', index, $event)"
        @input="emit('update', index, 'apiKey', ($event.target as HTMLInputElement).value)"
      />

      <div class="space-y-3 rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface-hover)] p-3">
        <div class="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="settings-secondary"
            size="sm"
            class="px-3 text-[11px] shadow-none"
            :disabled="busy"
            @click="emit('discoverModels', channel)"
          >
            {{ discoveryState?.status === 'loading' ? '获取中...' : '获取模型' }}
          </Button>
          <span
            :class="[
              'text-xs',
              discoveryState?.status === 'success'
                ? 'text-success'
                : discoveryState?.status === 'error'
                  ? 'text-danger'
                  : 'text-muted-text',
            ]"
          >
            {{
              discoveryState?.text || '支持 `/models` 的 OpenAI Compatible 渠道可自动拉取模型。'
            }}
          </span>
        </div>
        <p v-if="discoveryState?.hint" class="text-[11px] text-secondary-text">{{ discoveryState.hint }}</p>

        <div v-if="discoveredModels.length > 0">
          <label class="mb-2 block text-sm font-medium text-foreground">可选模型（可多选）</label>
          <div class="max-h-48 space-y-2 overflow-y-auto rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface)] p-3">
            <label v-for="model in discoveredModels" :key="model" class="flex items-center gap-2 text-sm text-secondary-text">
              <input
                type="checkbox"
                :checked="
                  selectedModels.some((selectedModel) =>
                    areModelsEquivalent(selectedModel, model, channel.protocol),
                  )
                "
                :disabled="busy"
                class="settings-input-checkbox h-4 w-4 rounded border-border/70 bg-base"
                @change="
                  emit(
                    'update',
                    index,
                    'models',
                    toggleModelSelection(channel.models, model, channel.protocol),
                  )
                "
              />
              <span>{{ model }}</span>
            </label>
          </div>
        </div>

        <Input
          :label="discoveredModels.length > 0 ? '手动模型（逗号分隔）' : '模型（逗号分隔）'"
          :value="channel.models"
          :disabled="busy"
          :placeholder="preset?.placeholderModels || MODEL_PLACEHOLDERS_BY_PROTOCOL[channel.protocol]"
          :hint="
            discoveredModels.length > 0
              ? '如有自定义模型名未出现在列表中，可继续手动补充，保存格式仍为逗号分隔。'
              : '若渠道不支持自动发现或请求失败，可直接手动填写模型列表。'
          "
          @input="emit('update', index, 'models', ($event.target as HTMLInputElement).value)"
        />

        <p v-if="manualOnlyModels.length > 0" class="text-[11px] text-secondary-text">
          额外手动模型：{{ manualOnlyModels.join('，') }}
        </p>
      </div>

      <div class="flex items-center gap-2 pt-1">
        <Button
          type="button"
          variant="settings-secondary"
          size="sm"
          class="px-3 text-[11px] shadow-none"
          :disabled="busy"
          @click="emit('test', channel, index)"
        >
          {{ testState?.status === 'loading' ? '测试中...' : '测试连接' }}
        </Button>
        <div v-if="testState?.text" class="space-y-1">
          <span
            :class="[
              'block text-xs',
              testState.status === 'success'
                ? 'text-success'
                : testState.status === 'error'
                  ? 'text-danger'
                  : 'text-muted-text',
            ]"
          >
            {{ testState.text }}
          </span>
          <p v-if="selectedModels[0]" class="text-[11px] text-secondary-text">
            基础连接测试默认使用模型列表首项：{{ selectedModels[0] }}
          </p>
          <p v-if="testState.hint" class="text-[11px] text-secondary-text">{{ testState.hint }}</p>
        </div>
      </div>

      <div class="space-y-3 rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface-hover)] p-3">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p class="text-[11px] font-medium text-muted-text">运行时能力检测（可选）</p>
            <p class="mt-0.5 text-[11px] text-secondary-text">仅在手动触发时发起真实 LLM 请求；多选可能需要 20-40 秒。</p>
          </div>
          <Button
            type="button"
            variant="settings-secondary"
            size="sm"
            class="px-3 text-[11px] shadow-none"
            :disabled="busy || capabilityBusy || selectedCapabilities.length === 0"
            @click="emit('checkCapabilities', channel)"
          >
            {{ capabilityBusy ? '检测中...' : '检测能力' }}
          </Button>
        </div>

        <div class="flex flex-wrap gap-2">
          <Tooltip v-for="option in RUNTIME_CAPABILITY_OPTIONS" :key="option.value" :content="option.hint">
            <label class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--settings-border)] bg-[var(--settings-surface)] px-2 py-1 text-[11px] text-secondary-text">
              <input
                type="checkbox"
                :checked="selectedCapabilities.includes(option.value)"
                :disabled="busy || capabilityBusy"
                class="settings-input-checkbox h-3.5 w-3.5 rounded border-border/70 bg-base"
                @change="emit('toggleCapability', channel, option.value)"
              />
              <span>{{ option.label }}</span>
            </label>
          </Tooltip>
        </div>

        <div v-if="capabilityState?.text" class="space-y-1">
          <p
            :class="[
              'text-xs',
              capabilityState.status === 'success'
                ? 'text-success'
                : capabilityState.status === 'error'
                  ? 'text-danger'
                  : 'text-muted-text',
            ]"
          >
            {{ capabilityState.text }}
          </p>
          <p v-if="capabilityState.hint" class="text-[11px] text-secondary-text">{{ capabilityState.hint }}</p>
        </div>

        <div v-if="Object.keys(capabilityResults).length > 0" class="flex flex-wrap gap-2">
          <template v-for="option in RUNTIME_CAPABILITY_OPTIONS" :key="option.value">
            <Tooltip
              v-if="capabilityResults[option.value]"
              :content="capabilityResults[option.value]!.message"
            >
              <span class="inline-flex">
                <Badge :variant="getCapabilityResultVariant(capabilityResults[option.value]!.status)">
                  {{ option.label }} {{ CAPABILITY_STATUS_LABELS[capabilityResults[option.value]!.status] }}
                </Badge>
              </span>
            </Tooltip>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

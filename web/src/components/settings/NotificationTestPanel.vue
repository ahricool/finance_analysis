<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { systemConfigApi } from '@/api/systemConfig';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Badge from '@/components/common/Badge.vue';
import Button from '@/components/common/Button.vue';
import InlineAlert from '@/components/common/InlineAlert.vue';
import Input from '@/components/common/Input.vue';
import Select from '@/components/common/Select.vue';
import SettingsSectionCard from '@/components/settings/SettingsSectionCard.vue';
import type {
  NotificationTestChannel,
  TestNotificationChannelResponse,
  SystemConfigUpdateItem,
} from '@/types/systemConfig';
import { Send } from 'lucide-vue-next';
import { computed, ref } from 'vue';

const CHANNEL_OPTIONS: Array<{ value: NotificationTestChannel; label: string }> = [
  { value: 'wechat', label: '企业微信' },
  { value: 'feishu', label: '飞书 Webhook' },
  { value: 'telegram', label: 'Telegram' },
  { value: 'email', label: '邮件' },
  { value: 'pushover', label: 'Pushover' },
  { value: 'ntfy', label: 'ntfy' },
  { value: 'gotify', label: 'Gotify' },
  { value: 'pushplus', label: 'PushPlus' },
  { value: 'serverchan3', label: 'Server酱3' },
  { value: 'custom', label: '自定义 Webhook' },
  { value: 'discord', label: 'Discord' },
  { value: 'slack', label: 'Slack' },
  { value: 'astrbot', label: 'AstrBot' },
];

const props = withDefaults(
  defineProps<{
    items: SystemConfigUpdateItem[];
    maskToken: string;
    disabled?: boolean;
  }>(),
  { disabled: false },
);

function clampTimeout(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 20;
  return Math.min(120, Math.max(1, parsed));
}

const channel = ref<NotificationTestChannel>('wechat');
const title = ref('DSA 通知测试');
const content = ref('这是一条来自 DSA Web 设置页的通知测试消息。');
const timeoutSeconds = ref('20');
const result = ref<TestNotificationChannelResponse | null>(null);
const error = ref<ParsedApiError | null>(null);
const isTesting = ref(false);

const normalizedItems = computed(() =>
  props.items.map((item) => ({ key: item.key, value: String(item.value ?? '') })),
);

async function runTest() {
  error.value = null;
  result.value = null;
  isTesting.value = true;
  try {
    const payload = await systemConfigApi.testNotificationChannel({
      channel: channel.value,
      items: normalizedItems.value,
      maskToken: props.maskToken,
      title: title.value.trim() || 'DSA 通知测试',
      content: content.value.trim() || '这是一条来自 DSA Web 设置页的通知测试消息。',
      timeoutSeconds: clampTimeout(timeoutSeconds.value),
    });
    result.value = payload;
  } catch (requestError: unknown) {
    error.value = getParsedApiError(requestError);
  } finally {
    isTesting.value = false;
  }
}

function onTimeoutBlur() {
  timeoutSeconds.value = String(clampTimeout(timeoutSeconds.value));
}
</script>

<template>
  <SettingsSectionCard title="通知测试" description="使用当前页面草稿发送一条真实测试通知；测试不会保存配置。">
    <template #actions>
      <Button
        type="button"
        variant="settings-primary"
        size="sm"
        :disabled="disabled || isTesting"
        :is-loading="isTesting"
        loading-text="测试中..."
        @click="runTest()"
      >
        <Send class="h-4 w-4" />
        发送测试
      </Button>
    </template>

    <div class="grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr_120px]">
      <Select
        label="渠道"
        :model-value="channel"
        :options="CHANNEL_OPTIONS"
        :disabled="disabled || isTesting"
        @update:model-value="channel = $event as NotificationTestChannel"
      />
      <Input
        label="标题"
        :value="title"
        maxlength="80"
        :disabled="disabled || isTesting"
        @input="title = ($event.target as HTMLInputElement).value"
      />
      <Input
        label="超时秒数"
        type="number"
        min="1"
        max="120"
        :value="timeoutSeconds"
        :disabled="disabled || isTesting"
        @input="timeoutSeconds = ($event.target as HTMLInputElement).value"
        @blur="onTimeoutBlur"
      />
    </div>

    <label class="block">
      <span class="mb-2 block text-sm font-medium text-foreground">正文</span>
      <textarea
        v-model="content"
        maxlength="1000"
        rows="4"
        :disabled="disabled || isTesting"
        class="input-surface input-focus-glow min-h-[112px] w-full resize-y rounded-xl border bg-transparent px-4 py-3 text-sm leading-6 text-foreground outline-none disabled:cursor-not-allowed disabled:opacity-50"
      />
    </label>

    <ApiErrorAlert v-if="error" :error="error" />

    <div v-if="result" class="space-y-3">
      <InlineAlert
        :variant="result.success ? 'success' : 'danger'"
        :title="result.success ? '测试成功' : '测试失败'"
      >
        <span>
          {{ result.message }}
          {{ typeof result.latencyMs === 'number' ? ` · ${result.latencyMs} ms` : '' }}
          {{ result.errorCode ? ` · ${result.errorCode}` : '' }}
        </span>
      </InlineAlert>

      <div v-if="result.attempts.length" class="space-y-2">
        <div
          v-for="(attempt, index) in result.attempts"
          :key="`${attempt.channel}-${index}-${attempt.target || 'target'}`"
          class="rounded-xl border settings-border bg-background/35 px-4 py-3"
        >
          <div class="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <Badge :variant="attempt.success ? 'success' : 'danger'">
                  {{ attempt.success ? '成功' : '失败' }}
                </Badge>
                <span class="text-sm font-medium text-foreground">Attempt {{ index + 1 }}</span>
                <span v-if="typeof attempt.httpStatus === 'number'" class="text-xs text-muted-text">
                  HTTP {{ attempt.httpStatus }}
                </span>
                <span v-if="typeof attempt.latencyMs === 'number'" class="text-xs text-muted-text">
                  {{ attempt.latencyMs }} ms
                </span>
              </div>
              <p class="mt-2 break-all text-xs leading-5 text-muted-text">
                {{ attempt.target || attempt.channel }}
              </p>
            </div>
            <Badge v-if="attempt.errorCode" :variant="attempt.retryable ? 'warning' : 'default'">
              {{ attempt.errorCode }}
            </Badge>
          </div>
          <p class="mt-2 text-xs leading-5 text-secondary-text">{{ attempt.message }}</p>
        </div>
      </div>
    </div>
  </SettingsSectionCard>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { Switch } from '@/components/ui/switch';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { fetchMinuteForecastPreference, saveMinuteForecastPreference } from '@/api/minuteForecast';
import { useAuthStore } from '@/stores/authStore';

const props = defineProps<{ symbol: string; contract?: boolean }>();
const auth = useAuthStore();
const canEdit = computed(() => auth.currentUser?.role === 'admin');
const enabled = ref<boolean | null>(null);
const busy = ref(false);
const error = ref<ParsedApiError | null>(null);
let generation = 0;
let controller: AbortController | undefined;

async function load() {
  const request = ++generation;
  controller?.abort();
  controller = new AbortController();
  enabled.value = null;
  busy.value = true;
  error.value = null;
  try {
    const result = await fetchMinuteForecastPreference(props.symbol, controller.signal, props.contract);
    if (request === generation) enabled.value = result.enabled;
  } catch (cause) {
    if (request === generation) error.value = getParsedApiError(cause);
  } finally {
    if (request === generation) busy.value = false;
  }
}

async function update(value: boolean) {
  if (busy.value || enabled.value === null || !canEdit.value) return;
  const request = ++generation;
  busy.value = true;
  error.value = null;
  try {
    const result = await saveMinuteForecastPreference(props.symbol, value, props.contract);
    if (request === generation) enabled.value = result.enabled;
  } catch (cause) {
    if (request === generation) error.value = getParsedApiError(cause);
  } finally {
    if (request === generation) busy.value = false;
  }
}
watch(() => props.symbol, load, { immediate: true });
onBeforeUnmount(() => { ++generation; controller?.abort(); });
</script>

<template>
  <section class="space-y-3 rounded-lg border p-4">
    <div class="flex items-center justify-between gap-4">
      <div class="space-y-1">
        <h3 class="text-sm font-semibold">
          1min K 预测
        </h3>
        <p class="text-xs text-muted-foreground">
          <template v-if="contract">
            Kronos · 连续 UTC 分钟 · 最多 60 根
          </template>
          <template v-else>
            全站共享 · 开启后使用已有的 1 分钟 K 线预测未来最多 60 根，截止当日收盘；数据不足时跳过。
          </template>
        </p>
      </div>
      <Switch
        aria-label="1min K 预测"
        :model-value="enabled === true"
        :disabled="busy || enabled === null || !canEdit"
        @update:model-value="update"
      />
    </div>
    <p
      v-if="!canEdit"
      class="text-xs text-muted-foreground"
    >
      仅管理员可修改此全站设置。
    </p>
    <p
      v-if="busy"
      role="status"
      class="text-xs text-muted-foreground"
    >
      {{ enabled === null ? '正在读取设置…' : '正在保存设置…' }}
    </p>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重新读取设置"
      @action="load"
    />
  </section>
</template>

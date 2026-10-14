<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { stocksApi, type StockIndustryMembership } from '@/api/stocks';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Badge } from '@/components/ui/badge';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';

const props = defineProps<{ code: string }>();
const industries = ref<StockIndustryMembership[]>([]);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const attempt = ref(0);
const observedAt = computed(() => industries.value[0]?.membersObservedAt);

watch(() => [props.code, attempt.value], async (_value, _previous, onCleanup) => {
  const controller = new AbortController();
  onCleanup(() => controller.abort());
  industries.value = []; error.value = null; loading.value = true;
  try {
    const result = await stocksApi.classification(props.code, controller.signal);
    if (!controller.signal.aborted) industries.value = result.memberships.industries ?? [];
  } catch (err) {
    if (!controller.signal.aborted && getParsedApiError(err).status !== 404) error.value = getParsedApiError(err);
  } finally {
    if (!controller.signal.aborted) loading.value = false;
  }
}, { immediate: true });
</script>

<template>
  <div
    class="mt-3 space-y-1.5 text-xs text-muted-foreground"
    data-testid="stock-industry-tags"
    aria-label="当前所属行业"
  >
    <p v-if="loading">
      正在加载所属行业…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
      action-label="重试行业"
      @action="attempt++"
    />
    <template v-else-if="industries.length">
      <div class="flex flex-wrap items-center gap-1.5">
        <span>所属行业</span>
        <Badge
          v-for="industry in industries"
          :key="industry.code"
          variant="secondary"
        >
          {{ industry.name }}
        </Badge>
      </div>
      <p>成分观测时间 {{ formatDateTimeInDisplayTimezone(observedAt) }} · 每周同步</p>
    </template>
    <p v-else>
      暂无所属行业数据
    </p>
  </div>
</template>

<script setup lang="ts">
import Badge from '@/components/common/Badge.vue';
import type { BacktestEngine, BacktestEngineKey } from '@/types/backtests';
import { marketLabels } from '@/utils/backtests';

defineProps<{ engines: BacktestEngine[]; modelValue: BacktestEngineKey }>();
const emit = defineEmits<{ 'update:modelValue': [value: BacktestEngineKey] }>();
</script>

<template>
  <div
    class="grid gap-3 md:grid-cols-2"
    data-testid="backtest-engine-selector"
  >
    <button
      v-for="engine in engines"
      :key="engine.key"
      type="button"
      :disabled="!engine.available"
      class="rounded-2xl border p-4 text-left transition disabled:cursor-not-allowed disabled:opacity-50"
      :class="modelValue === engine.key ? 'border-primary bg-primary/8 shadow-soft-card' : 'border-border/70 bg-card/70 hover:border-primary/50'"
      @click="emit('update:modelValue', engine.key)"
    >
      <div class="flex items-center gap-2">
        <strong class="text-sm text-foreground">{{ engine.name }}</strong>
        <Badge
          v-if="engine.recommended"
          variant="success"
        >
          推荐
        </Badge>
        <Badge
          v-if="engine.isDefault"
          variant="info"
        >
          默认
        </Badge>
        <span class="ml-auto text-xs text-muted-text">v{{ engine.version || '未知' }}</span>
      </div>
      <p class="mt-2 text-xs leading-5 text-secondary-text">
        {{ engine.description }}
      </p>
      <p class="mt-2 text-xs text-muted-text">
        支持市场：{{ engine.supportedMarkets.map((item) => marketLabels[item]).join('、') || '无' }}
      </p>
      <p
        v-if="!engine.available"
        class="mt-2 text-xs text-danger"
      >
        {{ engine.unavailableReason }}
      </p>
    </button>
  </div>
</template>

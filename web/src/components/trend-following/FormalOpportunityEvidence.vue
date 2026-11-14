<script setup lang="ts">
import { patternNames } from './opportunities';
import { formatFixed } from '@/utils/number';

defineProps<{ branches: Record<string, unknown>[] }>();
const number = (value: unknown) => formatFixed(value, { digits: 2 });
const periods = (value: unknown) => Array.isArray(value) ? value.join(' / ') : '—';
</script>

<template>
  <section
    v-if="branches.length"
    class="mt-3 space-y-2 rounded-lg border bg-muted/20 p-3"
    data-testid="formal-opportunity-evidence"
  >
    <p class="text-xs font-semibold">
      正式买点 · 冻结证据
    </p>
    <div
      v-for="branch in branches"
      :key="String(branch.structureId)"
      class="space-y-1 border-t pt-2 text-xs"
    >
      <p class="font-medium">
        {{ patternNames[String(branch.kind)] ?? branch.kind }} · 质量 {{ number(branch.qualityScore) }}
      </p>
      <p>触发 {{ number(branch.trigger) }} · 支撑 {{ number(branch.support) }} · 失效 {{ number(branch.invalidation) }}</p>
      <p class="text-muted-foreground">
        首次确认 {{ branch.firstConfirmedAt ?? '—' }} · 数据 {{ branch.dataAsOf ?? '—' }} · 背景 {{ periods(branch.backgroundPeriods) }}D
      </p>
    </div>
    <p class="text-xs leading-relaxed text-muted-foreground">
      价位为当时的前复权研究值，不直接作为实时委托价；同一结构跨周期只计一次。正式买点不代表盘中已确认。
    </p>
  </section>
</template>

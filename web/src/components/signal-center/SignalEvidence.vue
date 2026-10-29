<script setup lang="ts">
import { ScanLine } from 'lucide-vue-next';
import type { SignalEvidence } from '@/api/signalCenter';
withDefaults(defineProps<{ evidence: SignalEvidence[]; label?: string }>(), { label: '核验证据' });
function claimLabel(value: string) {
  if (value === 'thesis') return '整体结论';
  const [key, index] = value.split('.');
  return `${({ positive_signals: '支持依据', risks: '风险', invalidations: '失效条件' } as Record<string, string>)[key || ''] || key} ${Number(index) + 1}`;
}
</script>
<template>
  <details class="rounded-lg border">
    <summary class="flex cursor-pointer items-center gap-2 p-3 text-sm font-medium">
      <ScanLine class="size-4 text-muted-foreground" />{{ label }}<span class="ml-auto text-xs text-muted-foreground">{{ evidence.length }} 条</span>
    </summary>
    <div class="space-y-3 border-t p-3">
      <div
        v-for="fact in evidence"
        :key="fact.field"
        class="space-y-1 border-b pb-3 text-xs last:border-0 last:pb-0"
      >
        <p class="break-all font-mono text-muted-foreground">
          {{ fact.field }}
        </p>
        <p class="font-medium">
          {{ String(fact.value) }} <span class="font-normal text-muted-foreground">· {{ fact.dataAsOf }}</span>
        </p>
        <p
          v-if="fact.supports?.length"
          class="text-muted-foreground"
        >
          用于：{{ fact.supports.map(claimLabel).join(' · ') }}
        </p>
        <p class="leading-6">
          {{ fact.interpretation }}
        </p>
      </div>
      <p class="text-xs leading-5 text-muted-foreground">
        字段、数值与日期已按冻结快照校验；文字解释为模型判断。
      </p>
    </div>
  </details>
</template>

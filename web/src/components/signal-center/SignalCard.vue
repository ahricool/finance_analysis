<script setup lang="ts">
import type { SignalDetail } from '@/api/signalCenter';
import { formatDateTime } from '@/utils/format';
import { Badge } from '@/components/ui/badge';
import SignalEvaluation from './SignalEvaluation.vue';
defineProps<{ signal: SignalDetail }>();
const statuses = { pending: '分析中', completed: '已完成', failed: '分析失败，未产生信号', skipped: '数据不足，跳过' };
const sourceNames: Record<string, string> = { trend: 'Trend', quant: 'Quant', industry: '行业强度', etf: 'ETF', regime: '市场环境' };
const sourceStatuses: Record<string, string> = { available: '可用', missing: '缺失', stale: '过期', running: '运行中', failed: '读取失败', unsupported: '不适用' };
const confidence: Record<string, string> = { high: '高', medium: '中', low: '低' };
</script>

<template>
  <div
    class="space-y-4"
    data-testid="signal-card"
  >
    <div class="flex items-center gap-3">
      <strong class="text-xl">{{ signal.selectedSymbol || (signal.decision === 'NO_TRADE' ? '当日不交易' : '暂无交易信号') }}</strong>
      <Badge>{{ signal.decision || statuses[signal.status] }}</Badge>
      <span
        v-if="signal.confidence"
        class="text-sm text-muted-foreground"
      >信心：{{ confidence[signal.confidence] }}</span>
    </div>
    <template v-if="signal.analysis">
      <p class="whitespace-pre-wrap leading-relaxed">
        {{ signal.analysis.thesis }}
      </p>
      <div
        v-for="section in [{ label: '正向信号', items: signal.analysis.positiveSignals }, { label: '风险', items: signal.analysis.risks }, { label: '失效条件', items: signal.analysis.invalidations }]"
        :key="section.label"
      >
        <h4 class="mb-1 text-sm font-semibold">
          {{ section.label }}
        </h4>
        <ul
          v-if="section.items.length"
          class="list-disc space-y-1 pl-5 text-sm"
        >
          <li
            v-for="(item, i) in section.items"
            :key="i"
          >
            {{ item }}
          </li>
        </ul>
        <p
          v-else
          class="text-sm text-muted-foreground"
        >
          未列出
        </p>
      </div>
    </template>
    <p
      v-else
      class="text-sm text-muted-foreground"
    >
      {{ signal.status === 'skipped' ? signal.error : statuses[signal.status] }}
    </p>
    <SignalEvaluation
      v-if="signal.evaluation && signal.decision === 'BUY'"
      :evaluation="signal.evaluation"
    />
    <div class="border-t pt-3 text-xs text-muted-foreground space-y-1">
      <p>交易日期：{{ signal.signalDate }} · 生成时间：{{ signal.completedAt ? formatDateTime(signal.completedAt) : '尚未完成' }}</p>
      <p>输入采集：{{ formatDateTime(signal.candidateSnapshot.capturedAt) }} · 候选 {{ signal.candidateSnapshot.candidates.length }} 只</p>
      <p
        v-for="(source, name) in signal.candidateSnapshot.sourceAvailability"
        :key="name"
      >
        {{ sourceNames[name] || name }}：{{ sourceStatuses[source.status] || source.status }} · 数据日期 {{ source.dataAsOf || '—' }} · 生成 {{ source.generatedAt ? formatDateTime(source.generatedAt) : '—' }}
      </p>
      <p>模型：{{ signal.model || '—' }} · Prompt：{{ signal.promptVersion }}</p>
    </div>
  </div>
</template>

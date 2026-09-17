<script setup lang="ts">
import type { Pool } from '@/api/marketSentiment';
import { pct, money, flag } from './display';
defineProps<{ pool: Pool | null }>();
</script>
<template>
  <p
    v-if="!pool?.available"
    class="py-8 text-center text-muted-foreground"
  >
    未获取
  </p>
  <div
    v-else
    class="overflow-x-auto rounded-lg border"
  >
    <table class="w-full text-left text-xs">
      <thead class="bg-muted">
        <tr>
          <th>代码 / 名称</th><th>连板文本</th><th>涨跌幅</th><th>涨停时间</th><th>当前封单额</th><th>峰值封单额</th><th>留存比</th><th>原始涨停原因</th><th>ST / 未开板新股</th><th v-if="pool.kind !== 'limit_up'">
            补充字段
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="r in pool.items"
          :key="r.thscode"
          class="border-t align-top"
        >
          <td class="whitespace-nowrap">
            {{ r.thscode }}<br>{{ r.name }}
          </td><td class="whitespace-nowrap">
            {{ r.continueDayText ?? '—' }}<span
              v-if="pool.kind === 'limit_up' && r.consecutiveBoards == null"
              class="block text-muted-foreground"
            >连续性未确认</span>
          </td>
          <td>{{ pct(pool.kind === 'limit_up' ? r.priceChangeRatio : r.priceChangeRatioPct == null ? null : r.priceChangeRatioPct / 100) }}</td>
          <td>{{ r.limitUpTime ?? '—' }}</td><td>{{ money(r.sealMoney) }}</td><td>{{ money(r.maxSealMoney) }}</td><td>{{ pct(r.sealRetention) }}</td>
          <td class="min-w-48 max-w-96 break-words">
            {{ r.limitUpReason || '未提供原因' }}<span
              v-if="r.qualityIssues?.includes('abnormal_seal_retention')"
              class="block text-amber-600"
            >封单比值异常</span>
          </td><td>{{ flag(r.isSt) }} / {{ flag(r.isNew) }}</td>
          <td v-if="pool.kind !== 'limit_up'">
            {{ pool.kind === 'limit_down' ? `首次 / 最后跌停 ${r.firstLimitTime ?? '—'} / ${r.lastLimitTime ?? '—'}` : `开板次数 ${r.openTimes ?? '—'}` }}
          </td>
        </tr><tr v-if="!pool.items.length">
          <td
            colspan="10"
            class="py-8 text-center text-muted-foreground"
          >
            0 条符合当前筛选的记录
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
<style scoped>
th, td { padding: 0.75rem; }
</style>

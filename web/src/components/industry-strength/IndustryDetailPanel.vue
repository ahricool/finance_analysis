<script setup lang="ts">
import type { IndustryDetail, Constituents } from '@/api/industryStrength';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { breadthLabel, pct, num, delta, tone, stateLabels, stateColors } from './display';
import { formatDateTime } from '@/utils/format';
defineProps<{ detail: IndustryDetail; constituents: Constituents | null }>();
const ma = (value: boolean | null) => value == null ? '缺失' : value ? '上方' : '下方 / 持平';
</script>
<template>
  <Card data-testid="industry-detail">
    <CardHeader>
      <CardTitle class="flex items-center gap-4">
        {{ detail.current.industryName }} <span class="text-muted-foreground">#{{ detail.current.strengthRank }}</span><span
          class="text-sm"
          :style="{ color: stateColors[detail.current.state] }"
        >{{ stateLabels[detail.current.state] }}</span>
      </CardTitle><CardDescription>{{ detail.current.tradeDate }} · Strength {{ num(detail.current.strengthScore) }} · Δ5D {{ delta(detail.current.rankChange5D) }}</CardDescription>
    </CardHeader>
    <CardContent class="space-y-5">
      <div class="grid grid-cols-6 gap-3 text-sm">
        <div
          v-for="[label, value] in [['Return 5D', detail.current.ret5D], ['Return 10D', detail.current.ret10D], ['Return 20D', detail.current.ret20D], ['RS 5D', detail.current.rs5D], ['RS 10D', detail.current.rs10D], ['RS 20D', detail.current.rs20D]] as const"
          :key="label"
          class="rounded-lg bg-muted/50 p-3"
        >
          <p class="text-xs text-muted-foreground">
            {{ label }}
          </p><p
            class="mt-2 font-semibold"
            :class="tone(value)"
          >
            {{ pct(value) }}
          </p>
        </div>
      </div>
      <div class="grid grid-cols-6 gap-3 text-sm">
        <div>
          <p class="text-muted-foreground">
            加速度
          </p><p
            class="mt-2 font-semibold"
            :class="tone(detail.current.momentumAcceleration5D)"
          >
            {{ pct(detail.current.momentumAcceleration5D) }}
          </p>
        </div><div>
          <p class="text-muted-foreground">
            成交额脉冲
          </p><p class="mt-2 font-semibold">
            {{ num(detail.current.turnoverRatio5D) }}×
          </p>
        </div><div>
          <p class="text-muted-foreground">
            上涨广度
          </p><p class="mt-2 font-semibold">
            {{ breadthLabel(detail.current.upRatio, detail.current.upCount, detail.current.dailyValidCount) }}
          </p>
        </div><div>
          <p class="text-muted-foreground">
            MA5 上方
          </p><p class="mt-2 font-semibold">
            {{ breadthLabel(detail.current.aboveMa5Ratio, detail.current.aboveMa5Count, detail.current.ma5ValidCount) }}
          </p>
        </div><div>
          <p class="text-muted-foreground">
            MA20 上方
          </p><p class="mt-2 font-semibold">
            {{ breadthLabel(detail.current.aboveMa20Ratio, detail.current.aboveMa20Count, detail.current.ma20ValidCount) }}
          </p>
        </div><div>
          <p class="text-muted-foreground">
            等权涨跌代理
          </p><p class="mt-2 font-semibold">
            {{ pct(detail.current.equalWeightReturn) }}
          </p>
        </div>
      </div>
      <p class="text-xs text-muted-foreground">
        快照 Daily 有效成分 {{ detail.current.dailyValidCount }} / {{ detail.current.constituentCount }} · 上涨 {{ detail.current.upCount }} / 下跌 {{ detail.current.downCount }} / 平盘 {{ detail.current.flatCount }}。成分观察时间：{{ formatDateTime(detail.current.membersObservedAt) }}。历史广度为当时保存的观测值。
      </p>
      <details class="rounded-lg border p-3">
        <summary class="cursor-pointer text-sm font-medium">
          最近 20 个快照交易日 · 强度与广度历史
        </summary><div class="mt-3 max-h-64 overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead
                  v-for="label in ['日期', 'Rank', 'Strength', 'RS 5D', 'RS 10D', 'RS 20D', '加速度', '上涨广度', 'MA5', 'MA20', '成交脉冲']"
                  :key="label"
                >
                  {{ label }}
                </TableHead>
              </TableRow>
            </TableHeader><TableBody>
              <TableRow
                v-for="r in [...detail.history].reverse()"
                :key="r.tradeDate"
              >
                <TableCell>{{ r.tradeDate }}</TableCell><TableCell>{{ r.strengthRank }}</TableCell><TableCell>{{ num(r.strengthScore) }}</TableCell><TableCell
                  v-for="k in (['rs5D', 'rs10D', 'rs20D', 'momentumAcceleration5D'] as const)"
                  :key="k"
                >
                  {{ pct(r[k]) }}
                </TableCell><TableCell>{{ breadthLabel(r.upRatio, r.upCount, r.dailyValidCount) }}</TableCell><TableCell>{{ breadthLabel(r.aboveMa5Ratio, r.aboveMa5Count, r.ma5ValidCount) }}</TableCell><TableCell>{{ breadthLabel(r.aboveMa20Ratio, r.aboveMa20Count, r.ma20ValidCount) }}</TableCell><TableCell>{{ num(r.turnoverRatio5D) }}×</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </details>
      <div class="border-t pt-4">
        <h3 class="font-semibold">
          当前成分股 · 最新完整交易日收盘观察
        </h3><p class="mt-2 text-xs leading-6 text-muted-foreground">
          当前成分股不代表历史成分。下表不随历史日期切换；当前成分股等权涨跌仅为行业内部广度代理，不代表行业指数贡献。价格为前复权收盘价，MA 使用同日完整日线。
        </p>
      </div>
      <template v-if="constituents">
        <p class="text-xs text-muted-foreground">
          行情日期 {{ constituents.tradeDate }} · 成分获取时间 {{ formatDateTime(constituents.membersObservedAt) }} · Daily {{ constituents.dailyValidCount }} / {{ constituents.constituentCount }} · MA5 {{ constituents.ma5ValidCount }} / {{ constituents.constituentCount }} · MA20 {{ constituents.ma20ValidCount }} / {{ constituents.constituentCount }} · 按涨跌幅降序，缺失排最后
        </p>
        <div class="max-h-80 overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead
                  v-for="label in ['股票', '收盘价', '涨跌幅', 'MA5', 'MA20', '成交额']"
                  :key="label"
                >
                  {{ label }}
                </TableHead>
              </TableRow>
            </TableHeader><TableBody>
              <TableRow
                v-for="r in constituents.items"
                :key="r.code"
              >
                <TableCell>{{ r.name }} <span class="ml-2 text-xs text-muted-foreground">{{ r.code }}</span></TableCell><TableCell>{{ num(r.price) }}</TableCell><TableCell :class="tone(r.changePct)">
                  {{ pct(r.changePct) }}
                </TableCell><TableCell>{{ ma(r.aboveMa5) }}</TableCell><TableCell>{{ ma(r.aboveMa20) }}</TableCell><TableCell>{{ r.amount == null ? '—' : `${(r.amount / 1e8).toFixed(2)} 亿` }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
      </template>
    </CardContent>
  </Card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import type { IndustrySnapshot } from '@/api/industryStrength';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { breadthLabel, pct, num, delta, tone, stateColors, stateLabels } from './display';
const props = defineProps<{ rows: IndustrySnapshot[]; selected: string }>();
const emit = defineEmits<{ select: [code: string] }>();
const columns = [
  ['strengthRank', 'Rank'], ['industryName', '行业'], ['state', '状态'], ['strengthScore', 'Strength'],
  ['rankChange1D', 'Δ1D'], ['rankChange3D', 'Δ3D'], ['rs5D', 'RS 5D'], ['rs10D', 'RS 10D'], ['rs20D', 'RS 20D'],
  ['momentumAcceleration5D', '加速度'], ['upRatio', '上涨广度'], ['aboveMa5Ratio', 'MA5 上方'], ['aboveMa20Ratio', 'MA20 上方'], ['turnoverRatio5D', '成交脉冲'],
] as const;
type SortKey = typeof columns[number][0];
const sort = ref<SortKey>('strengthRank'); const descending = ref(false);
function changeSort(key: SortKey) { if (sort.value === key) descending.value = !descending.value; else { sort.value = key; descending.value = !['strengthRank', 'industryName', 'state'].includes(key); } }
const sorted = computed(() => [...props.rows].sort((a, b) => {
  const av = a[sort.value]; const bv = b[sort.value];
  if (av == null) return bv == null ? 0 : 1;
  if (bv == null) return -1;
  return (typeof av === 'string' ? av.localeCompare(String(bv)) : Number(av) - Number(bv)) * (descending.value ? -1 : 1);
}));
</script>
<template>
  <div
    class="max-h-[560px] overflow-auto rounded-xl border"
    data-testid="industry-ranking"
  >
    <Table class="whitespace-nowrap text-xs">
      <TableHeader class="sticky top-0 z-10 bg-background">
        <TableRow>
          <TableHead
            v-for="[key, label] in columns"
            :key="key"
            :aria-sort="sort === key ? (descending ? 'descending' : 'ascending') : 'none'"
          >
            <button
              class="py-3 font-medium"
              @click="changeSort(key)"
            >
              {{ label }} {{ sort === key ? (descending ? '↓' : '↑') : '' }}
            </button>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <TableRow
          v-for="row in sorted"
          :key="row.industryCode"
          :data-state="row.industryCode === selected ? 'selected' : undefined"
        >
          <TableCell class="text-base font-semibold tabular-nums">
            {{ row.strengthRank }}
          </TableCell>
          <TableCell>
            <Button
              variant="link"
              class="h-auto p-0 font-semibold text-foreground"
              @click="emit('select', row.industryCode)"
            >
              {{ row.industryName }}
            </Button>
          </TableCell>
          <TableCell>
            <span
              class="rounded-full border px-2 py-1"
              :style="{ color: stateColors[row.state] }"
            >{{ stateLabels[row.state] }}</span>
          </TableCell>
          <TableCell class="font-semibold tabular-nums">
            {{ num(row.strengthScore) }}
          </TableCell>
          <TableCell :class="tone(row.rankChange1D)">
            {{ delta(row.rankChange1D) }}
          </TableCell><TableCell :class="tone(row.rankChange3D)">
            {{ delta(row.rankChange3D) }}
          </TableCell>
          <TableCell
            v-for="key in (['rs5D', 'rs10D', 'rs20D'] as const)"
            :key="key"
            :class="tone(row[key])"
          >
            {{ pct(row[key]) }}
          </TableCell>
          <TableCell
            :class="tone(row.momentumAcceleration5D)"
            class="font-semibold"
          >
            {{ pct(row.momentumAcceleration5D) }}
          </TableCell>
          <TableCell class="font-semibold">
            {{ breadthLabel(row.upRatio, row.upCount, row.dailyValidCount) }}
          </TableCell><TableCell>{{ breadthLabel(row.aboveMa5Ratio, row.aboveMa5Count, row.ma5ValidCount) }}</TableCell><TableCell>{{ breadthLabel(row.aboveMa20Ratio, row.aboveMa20Count, row.ma20ValidCount) }}</TableCell><TableCell>{{ num(row.turnoverRatio5D) }}×</TableCell>
        </TableRow>
      </TableBody>
    </Table>
  </div>
</template>

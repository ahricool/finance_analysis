<script setup lang="ts">
import { computed, ref } from 'vue';
import type { IndustrySnapshot, IndustryState } from '@/api/industryStrength';
import { CircleHelp } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import {
  coverageInsufficient,
  filterRankingRows,
  formatRankingCell,
  PERCENT_KEYS,
  POINT_KEYS,
  RANK_DELTA_KEYS,
  rankingColumns,
  stateBadgeClass,
  stateCounts,
  stateExplanations,
  stateLabels,
  STATE_ORDER,
  toneClass,
  breadthCountsLabel,
  breadthMissingReason,
  type RankingColumnKey,
} from './display';

const props = defineProps<{ rows: IndustrySnapshot[]; selected: string }>();
const emit = defineEmits<{ select: [code: string] }>();

const query = ref('');
const stateFilter = ref<'ALL' | IndustryState>('ALL');
const columnMode = ref<'core' | 'full'>('core');
const sortKey = ref<RankingColumnKey>('strengthRank');
const descending = ref(false);
const scroller = ref<HTMLElement | null>(null);

const visibleColumns = computed(() => rankingColumns.filter((column) => columnMode.value === 'full' || column.core));
const visibleKeys = computed(() => new Set(visibleColumns.value.map((column) => column.key)));
const hiddenSort = computed(() => columnMode.value === 'core' && !visibleKeys.value.has(sortKey.value));
const counts = computed(() => stateCounts(props.rows));
const filtered = computed(() => filterRankingRows(props.rows, query.value, stateFilter.value));
const sorted = computed(() => [...filtered.value].sort((a, b) => {
  const key = sortKey.value;
  if (key === 'industryName') {
    return a.industryName.localeCompare(b.industryName, 'zh-CN') * (descending.value ? -1 : 1);
  }
  if (key === 'state') {
    return stateLabels[a.state].localeCompare(stateLabels[b.state], 'zh-CN') * (descending.value ? -1 : 1);
  }
  const av = a[key];
  const bv = b[key];
  if (av == null) return bv == null ? 0 : 1;
  if (bv == null) return -1;
  return (Number(av) - Number(bv)) * (descending.value ? -1 : 1);
}));
const hasFilters = computed(() => query.value.trim() !== '' || stateFilter.value !== 'ALL');
const hiddenSortLabel = computed(() => rankingColumns.find((column) => column.key === sortKey.value)?.label ?? sortKey.value);

function changeSort(key: RankingColumnKey) {
  if (sortKey.value === key) descending.value = !descending.value;
  else {
    sortKey.value = key;
    descending.value = !['strengthRank', 'industryName', 'state'].includes(key);
  }
}

function clearFilters() {
  query.value = '';
  stateFilter.value = 'ALL';
}

function ratioOf(row: IndustrySnapshot, key: RankingColumnKey): number | null {
  if (key === 'upRatio') return row.upRatio;
  if (key === 'aboveMa5Ratio') return row.aboveMa5Ratio;
  if (key === 'aboveMa20Ratio') return row.aboveMa20Ratio;
  return null;
}

function countsOf(row: IndustrySnapshot, key: RankingColumnKey): { count: number | null; valid: number | null; kind: 'up' | 'ma' } {
  if (key === 'upRatio') return { count: row.upCount, valid: row.dailyValidCount, kind: 'up' };
  if (key === 'aboveMa5Ratio') return { count: row.aboveMa5Count, valid: row.ma5ValidCount, kind: 'ma' };
  return { count: row.aboveMa20Count, valid: row.ma20ValidCount, kind: 'ma' };
}

function stickyHead(key: RankingColumnKey) {
  if (key === 'strengthRank') return 'sticky left-0 z-30 min-w-14 bg-background';
  if (key === 'industryName') return 'sticky left-14 z-30 min-w-40 bg-background shadow-[4px_0_8px_-6px_hsl(var(--foreground)/0.25)]';
  return '';
}

function stickyCell(key: RankingColumnKey, selected: boolean) {
  const bg = selected ? 'bg-muted' : 'bg-background group-hover:bg-muted/50';
  if (key === 'strengthRank') return `sticky left-0 z-10 min-w-14 ${bg}`;
  if (key === 'industryName') return `sticky left-14 z-10 min-w-40 shadow-[4px_0_8px_-6px_hsl(var(--foreground)/0.18)] ${bg}`;
  return '';
}

defineExpose({ scroller, query, stateFilter, columnMode, sortKey, descending, clearFilters });
</script>

<template>
  <div
    class="space-y-3"
    data-testid="industry-ranking-panel"
  >
    <div class="flex flex-wrap items-end gap-3">
      <label class="grid min-w-48 flex-1 gap-1 text-sm">
        <span class="text-muted-foreground">搜索行业</span>
        <Input
          v-model="query"
          data-testid="industry-search"
          placeholder="名称或代码"
          aria-label="搜索行业名称或代码"
        />
      </label>
      <div class="grid gap-1 text-sm">
        <span class="text-muted-foreground">状态筛选</span>
        <div
          class="flex flex-wrap gap-1"
          data-testid="industry-state-filter"
        >
          <Button
            size="sm"
            :variant="stateFilter === 'ALL' ? 'secondary' : 'ghost'"
            :aria-pressed="stateFilter === 'ALL'"
            @click="stateFilter = 'ALL'"
          >
            全部 {{ counts.ALL }}
          </Button>
          <Button
            v-for="state in STATE_ORDER"
            :key="state"
            size="sm"
            :variant="stateFilter === state ? 'secondary' : 'ghost'"
            :aria-pressed="stateFilter === state"
            @click="stateFilter = state"
          >
            {{ stateLabels[state] }} {{ counts[state] }}
          </Button>
        </div>
      </div>
      <div class="ml-auto flex flex-wrap items-center gap-2">
        <div
          class="flex rounded-lg border p-0.5"
          data-testid="industry-column-mode"
        >
          <Button
            size="sm"
            :variant="columnMode === 'core' ? 'secondary' : 'ghost'"
            :aria-pressed="columnMode === 'core'"
            @click="columnMode = 'core'"
          >
            核心指标
          </Button>
          <Button
            size="sm"
            :variant="columnMode === 'full' ? 'secondary' : 'ghost'"
            :aria-pressed="columnMode === 'full'"
            @click="columnMode = 'full'"
          >
            完整指标
          </Button>
        </div>
        <Button
          v-if="hasFilters"
          size="sm"
          variant="outline"
          data-testid="industry-clear-filters"
          @click="clearFilters"
        >
          清除筛选
        </Button>
      </div>
    </div>
    <p
      class="text-sm text-muted-foreground"
      data-testid="industry-filter-count"
    >
      当前显示 {{ filtered.length }} / 全部 {{ rows.length }} 个行业
    </p>
    <p
      v-if="hiddenSort"
      class="rounded-lg border border-amber-500/40 px-3 py-2 text-sm text-amber-800 dark:text-amber-200"
      data-testid="industry-hidden-sort"
    >
      当前按「{{ hiddenSortLabel }}」排序，该列仅在完整指标中可见。
      <Button
        size="sm"
        variant="ghost"
        class="ml-2 h-7"
        @click="columnMode = 'full'"
      >
        查看完整指标
      </Button>
    </p>
    <div
      v-if="!filtered.length"
      class="rounded-xl border py-16 text-center text-muted-foreground"
      data-testid="industry-ranking-empty-filter"
    >
      没有匹配筛选的行业。
    </div>
    <div
      v-else
      ref="scroller"
      class="max-h-[min(70vh,40rem)] overflow-auto rounded-xl border"
      data-testid="industry-ranking"
    >
      <Table
        container-class="overflow-visible"
        class="text-sm"
      >
        <TableHeader class="sticky top-0 z-20 bg-background">
          <TableRow>
            <TableHead
              v-for="column in visibleColumns"
              :key="column.key"
              :class="[
                stickyHead(column.key),
                column.numeric ? 'text-right' : '',
              ]"
              :aria-sort="sortKey === column.key ? (descending ? 'descending' : 'ascending') : 'none'"
            >
              <div
                class="inline-flex items-center gap-1 py-3"
                :class="column.numeric ? 'w-full justify-end' : ''"
              >
                <button
                  type="button"
                  class="font-medium focus-visible:ring-2 focus-visible:ring-ring"
                  @click="changeSort(column.key)"
                >
                  {{ column.unit ? `${column.short}（${column.unit}）` : column.short }}
                  <span class="text-muted-foreground">{{ sortKey === column.key ? (descending ? '↓' : '↑') : '' }}</span>
                </button>
                <TooltipProvider :delay-duration="150">
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button
                        type="button"
                        class="text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                        :aria-label="`查看${column.label}说明`"
                        @click.stop
                      >
                        <CircleHelp class="size-3.5" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>{{ column.hint }}</TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="row in sorted"
            :key="row.industryCode"
            class="group cursor-pointer"
            :data-state="row.industryCode === selected ? 'selected' : undefined"
            @click="emit('select', row.industryCode)"
          >
            <TableCell
              v-for="column in visibleColumns"
              :key="column.key"
              :class="[
                stickyCell(column.key, row.industryCode === selected),
                column.numeric ? 'text-right tabular-nums' : '',
                RANK_DELTA_KEYS.has(column.key) || POINT_KEYS.has(column.key) || PERCENT_KEYS.has(column.key) && column.key.startsWith('ret')
                  ? toneClass(row[column.key] as number | null)
                  : '',
                column.key === 'strengthScore' || column.key === 'strengthRank' ? 'font-semibold' : '',
              ]"
            >
              <template v-if="column.key === 'industryName'">
                <div class="flex min-w-40 flex-col items-start">
                  <Button
                    variant="link"
                    class="h-auto p-0 font-semibold text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                    @click.stop="emit('select', row.industryCode)"
                  >
                    {{ row.industryName }}
                  </Button>
                  <span class="text-xs text-muted-foreground">{{ row.industryCode }}</span>
                  <span
                    v-if="coverageInsufficient(row)"
                    class="mt-1 rounded border border-amber-500/40 px-1.5 py-0.5 text-[11px] text-amber-800 dark:text-amber-200"
                  >覆盖不足</span>
                </div>
              </template>
              <template v-else-if="column.key === 'state'">
                <TooltipProvider :delay-duration="150">
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <span
                        class="inline-flex rounded-full border px-2 py-0.5 text-xs"
                        :class="stateBadgeClass[row.state]"
                      >{{ stateLabels[row.state] }}</span>
                    </TooltipTrigger>
                    <TooltipContent>{{ stateExplanations[row.state] }}</TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </template>
              <template v-else-if="PERCENT_KEYS.has(column.key) && column.key.includes('Ratio') || column.key === 'upRatio' || column.key === 'aboveMa5Ratio' || column.key === 'aboveMa20Ratio'">
                <TooltipProvider :delay-duration="150">
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button
                        type="button"
                        class="ml-auto flex items-center justify-end gap-2 focus-visible:ring-2 focus-visible:ring-ring"
                        :aria-label="breadthMissingReason(row, column.key === 'upRatio' ? 'up' : column.key === 'aboveMa5Ratio' ? 'ma5' : 'ma20') || breadthCountsLabel(countsOf(row, column.key).count, countsOf(row, column.key).valid, countsOf(row, column.key).kind)"
                        @click.stop
                      >
                        <span
                          v-if="ratioOf(row, column.key) != null"
                          class="h-1.5 w-12 overflow-hidden rounded-full bg-muted"
                          aria-hidden="true"
                        >
                          <span
                            class="block h-full rounded-full bg-foreground/70"
                            :style="{ width: `${Math.max(0, Math.min(100, (ratioOf(row, column.key) ?? 0) * 100))}%` }"
                          />
                        </span>
                        <span class="tabular-nums">{{ formatRankingCell(row, column.key) }}</span>
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {{ breadthMissingReason(row, column.key === 'upRatio' ? 'up' : column.key === 'aboveMa5Ratio' ? 'ma5' : 'ma20') || breadthCountsLabel(countsOf(row, column.key).count, countsOf(row, column.key).valid, countsOf(row, column.key).kind) }}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </template>
              <template v-else>
                {{ formatRankingCell(row, column.key) }}
              </template>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue';
import { confluenceApi as api, type ConfluenceRanking, type ConfluenceItem, type Market, type SignalKey } from '@/api/confluence';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { useAuth } from '@/composables/useAuth';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '@/components/ui/table';
import { formatDateTime } from '@/utils/format';

const { currentUser } = useAuth();
const market = ref<Market>('CN'); const tradeDate = ref(''); const dates = ref<string[]>([]);
const minSignals = ref<number | null>(null); const minScore = ref(0); const industry = ref(''); const lifecycle = ref('');
const earlyOnly = ref(false); const topIndustry = ref(false); const strongOnly = ref(false);
const result = shallowRef<ConfluenceRanking | null>(null); const selected = shallowRef<ConfluenceItem | null>(null);
const error = shallowRef<ParsedApiError | null>(null); const loading = ref(false); const submitting = ref(false);
const taskId = ref(''); const dialogOpen = ref(false);
const keys: SignalKey[] = ['industry', 'trend', 'quant', 'etf', 'dragonTiger'];
const labels: Record<SignalKey, string> = { industry: '行业', trend: '趋势', quant: 'Quant', etf: 'ETF', dragonTiger: '龙虎榜资金' };
const states = { positive: '正向', neutral: '中性', negative: '负向', unavailable: '无数据' };
const fields: Record<SignalKey, [string, string][]> = {
  industry: [['industryName', '行业'], ['strengthRank', '排名'], ['strengthScore', '强度'], ['state', '状态'], ['rankChange1D', '1D 排名变化'], ['rankChange3D', '3D 排名变化'], ['rankChange5D', '5D 排名变化'], ['momentumAcceleration5D', '5D 增强'], ['membersObservedAt', '成分观测时间']],
  trend: [['trendLifecycle', 'Lifecycle'], ['state', 'State'], ['trendScore', 'Trend Score'], ['rank', '排名'], ['previousRank', '前次排名'], ['previousTradeDate', '前次日期'], ['trendDurationDays', '持续天数'], ['fragilityScore', 'Fragility'], ['trendAcceleration', 'Acceleration'], ['trendQuality', 'Quality'], ['rsScore', 'RS Score']],
  quant: [['universeRank', '排名'], ['finalScore', 'Final Score'], ['signal', 'Signal'], ['predictedReturn', 'Prediction'], ['crossSectionScore', '横截面分数'], ['modelVersion', '模型版本']],
  etf: [['code', '关联 ETF'], ['rank', '排名'], ['state', 'State'], ['compositeScore', 'Composite'], ['entryScore', 'Entry Score'], ['rankChange1D', '1D 排名变化'], ['rankChange3D', '3D 排名变化'], ['rankChange5D', '5D 排名变化']],
  dragonTiger: [['rangeDays', '榜单窗口（天）'], ['netInflow', '净流入'], ['institutionNetInflow', '机构资金'], ['hotMoneyNetInflow', '游资资金']],
};
let generation = 0;
async function load(reset = false) {
  const token = ++generation; loading.value = true; error.value = null; result.value = null;
  selected.value = null; dialogOpen.value = false;
  if (reset) { tradeDate.value = ''; dates.value = []; }
  try {
    const [ranking, availableDates] = await Promise.all([
      api.ranking({ market: market.value, trade_date: tradeDate.value || undefined, min_score: Number(minScore.value),
        min_signals: minSignals.value === null ? undefined : Number(minSignals.value), industry: industry.value || undefined, lifecycle: lifecycle.value || undefined,
        early_only: earlyOnly.value, top_industry: topIndustry.value, strong_only: strongOnly.value, limit: 200 }),
      api.dates(market.value),
    ]);
    if (token !== generation) return;
    result.value = ranking; dates.value = availableDates;
    if (minSignals.value === null) minSignals.value = ranking.rules.minSignals;
  } catch (cause) { if (token === generation) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
function show(row: ConfluenceItem) { selected.value = row; dialogOpen.value = true; }
async function run() {
  submitting.value = true; error.value = null; taskId.value = '';
  try { taskId.value = (await api.run(market.value, tradeDate.value || undefined)).taskId; }
  catch (cause) { error.value = getParsedApiError(cause); }
  finally { submitting.value = false; }
}
function flowRecords(row: ConfluenceItem) { return (row.signals.dragonTiger.evidence.records ?? []) as Array<Record<string, unknown>>; }
function flowConcepts(row: ConfluenceItem) { return (row.signals.dragonTiger.evidence.conceptFlows ?? []) as Array<Record<string, unknown>>; }
function evidence(row: ConfluenceItem, key: SignalKey, field: string) { return row.signals[key].evidence[field] ?? '—'; }
onMounted(() => { void load(); });
onBeforeUnmount(() => { ++generation; });
</script>

<template>
  <div
    class="space-y-5"
    data-testid="confluence-page"
  >
    <PageHeader
      title="多信号共振"
      description="面向 2–14 天的正式结果交叉确认。先看证据与覆盖，再看分数。"
    >
      <template #actions>
        <Button
          v-if="currentUser?.role === 'admin'"
          variant="outline"
          :disabled="submitting"
          @click="run"
        >
          生成快照
        </Button>
        <Button
          :disabled="loading"
          @click="load()"
        >
          刷新
        </Button>
      </template>
    </PageHeader>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <p
      v-if="taskId"
      class="text-sm text-muted-foreground"
    >
      任务已提交：{{ taskId }}。完成后刷新查看。
    </p>
    <div class="flex flex-wrap items-end gap-3 rounded-lg border p-4">
      <label class="space-y-1 text-sm">市场<select
        v-model="market"
        aria-label="市场"
        class="block h-9 rounded-md border bg-background px-3"
        @change="load(true)"
      ><option>CN</option><option>US</option></select></label>
      <label class="space-y-1 text-sm">快照日期<select
        v-model="tradeDate"
        aria-label="快照日期"
        class="block h-9 rounded-md border bg-background px-3"
      ><option value="">最新</option><option
        v-for="day in dates"
        :key="day"
      >{{ day }}</option></select></label>
      <label class="space-y-1 text-sm">最低有效维度<Input
        v-model="minSignals"
        aria-label="最低有效维度"
        class="w-28"
        type="number"
        min="1"
        max="5"
      /></label>
      <label class="space-y-1 text-sm">最低分数<Input
        v-model="minScore"
        aria-label="最低分数"
        class="w-24"
        type="number"
        min="0"
        max="100"
      /></label>
      <label class="space-y-1 text-sm">行业<Input
        v-model="industry"
        aria-label="行业"
        class="w-32"
        placeholder="名称或代码"
      /></label>
      <label class="space-y-1 text-sm">Lifecycle<select
        v-model="lifecycle"
        aria-label="Lifecycle"
        class="block h-9 rounded-md border bg-background px-3"
      ><option value="">全部</option><option
        v-for="phase in ['IGNITION', 'EMERGING', 'EXPANSION', 'MATURE', 'EXHAUSTION', 'BROKEN']"
        :key="phase"
      >{{ phase }}</option></select></label>
      <label class="flex items-center gap-2 text-sm"><input
        v-model="earlyOnly"
        type="checkbox"
      >仅 IGNITION / EMERGING</label>
      <label class="flex items-center gap-2 text-sm"><input
        v-model="topIndustry"
        type="checkbox"
      >行业 Top10</label>
      <label class="flex items-center gap-2 text-sm"><input
        v-model="strongOnly"
        type="checkbox"
      >Strong Confluence</label>
      <Button
        :disabled="loading"
        @click="load()"
      >
        筛选
      </Button>
    </div>
    <p class="text-sm text-muted-foreground">
      正向贡献全权重，中性贡献一半，负向为 0；无数据不参与分母。至少 {{ result?.rules.minSignals ?? '—' }} 个有效维度进入默认榜单。V1 启发式规则，未经回测验证。
    </p>
    <p
      v-if="loading"
      role="status"
    >
      正在读取正式快照…
    </p>
    <template v-if="result">
      <div class="grid grid-cols-4 gap-4">
        <div class="rounded-lg border p-4">
          <p class="text-sm text-muted-foreground">
            Strong Confluence
          </p><p class="text-2xl font-semibold">
            {{ result.summary.strongConfluence }}
          </p><p class="text-xs text-muted-foreground">
            至少 {{ result.rules.strongMinSignals }} 维 / {{ result.rules.strongMinPositive }} 正向 / {{ result.rules.strongMinScore }} 分
          </p>
        </div>
        <div class="rounded-lg border p-4">
          <p class="text-sm text-muted-foreground">
            IGNITION + Top Industry
          </p><p class="text-2xl font-semibold">
            {{ result.summary.ignitionIndustryStrong }}
          </p>
        </div>
        <div class="rounded-lg border p-4">
          <p class="text-sm text-muted-foreground">
            Top Industry 共振股票
          </p><p class="text-2xl font-semibold">
            {{ result.summary.topIndustryConfluence }}
          </p>
        </div>
        <div class="rounded-lg border p-4">
          <p class="text-sm text-muted-foreground">
            快照目标日期
          </p><p class="text-xl font-semibold">
            {{ result.tradeDate ?? '暂无快照' }}
          </p><p class="text-xs text-muted-foreground">
            生成 {{ result.generatedAt ? formatDateTime(result.generatedAt) : '—' }}
          </p>
        </div>
      </div>
      <div class="rounded-lg border p-4 text-sm space-y-2">
        <p class="font-medium">
          来源覆盖 · 各维度日期独立，可能早于目标日期
        </p>
        <p
          v-for="(source, key) in result.sourceAvailability"
          :key="key"
        >
          <span class="font-medium">{{ labels[key] }}</span> · {{ source.tradeDate ?? '无正式日期' }} · {{ source.count }} 条 · {{ source.status === 'available' ? '可用' : source.status === 'failed' ? '读取失败' : '不可用' }}<span v-if="source.reason"> · {{ source.reason }}</span>
        </p>
        <p
          v-if="market === 'US'"
          class="text-muted-foreground"
        >
          US 当前可能仅有趋势与 Quant 两个维度。可将最低维度设为 2 查看有限证据，不能因此认定为高共振。
        </p>
      </div>
      <p class="text-sm text-muted-foreground">
        匹配 {{ result.total }} 只，显示前 {{ result.items.length }} 只；摘要为整日统计。Signals = 正向 / 有效维度（共 5 维）。
      </p>
      <div class="rounded-lg border overflow-x-auto">
        <Table>
          <TableHeader><TableRow><TableHead>股票</TableHead><TableHead>Confluence</TableHead><TableHead>Signals</TableHead><TableHead>Industry</TableHead><TableHead>Lifecycle / Fragility</TableHead><TableHead>Quant Rank</TableHead><TableHead>ETF Rank</TableHead><TableHead>龙虎榜资金</TableHead><TableHead>Why Confluence</TableHead></TableRow></TableHeader>
          <TableBody>
            <TableRow
              v-for="row in result.items"
              :key="row.code"
            >
              <TableCell>
                <Button
                  variant="link"
                  class="h-auto p-0"
                  @click="show(row)"
                >
                  {{ row.name }}<br>{{ row.code }}
                </Button>
              </TableCell>
              <TableCell>
                <strong>{{ row.confluenceScore?.toFixed(1) ?? '—' }}</strong><p class="text-xs text-muted-foreground">
                  权重 {{ row.availableWeight }}/100
                </p><Badge
                  v-if="!row.eligible"
                  variant="outline"
                >
                  证据不足
                </Badge>
              </TableCell>
              <TableCell>{{ row.positiveSignalCount }}/{{ row.availableSignalCount }}</TableCell>
              <TableCell>
                {{ evidence(row, 'industry', 'industryName') }}<p class="text-xs">
                  Rank {{ evidence(row, 'industry', 'strengthRank') }}
                </p>
              </TableCell>
              <TableCell>
                {{ evidence(row, 'trend', 'trendLifecycle') }}<p class="text-xs">
                  Fragility {{ evidence(row, 'trend', 'fragilityScore') }}
                </p>
              </TableCell>
              <TableCell>{{ evidence(row, 'quant', 'universeRank') }}</TableCell><TableCell>{{ evidence(row, 'etf', 'rank') }}</TableCell>
              <TableCell>{{ row.signals.dragonTiger.status === 'unavailable' ? '无数据' : evidence(row, 'dragonTiger', 'netInflow') }}</TableCell>
              <TableCell class="max-w-80 whitespace-normal">
                <div class="flex flex-wrap gap-1 mb-2">
                  <Badge
                    v-for="key in keys"
                    :key="key"
                    variant="outline"
                    :class="{ 'text-market-up': row.signals[key].status === 'positive', 'text-market-down': row.signals[key].status === 'negative', 'text-muted-foreground': row.signals[key].status === 'unavailable' }"
                  >
                    {{ labels[key] }} {{ states[row.signals[key].status] }} {{ row.signals[key].score ?? '—' }}
                  </Badge>
                </div><p
                  v-for="key in keys.filter(k => row.signals[k].status !== 'unavailable')"
                  :key="key"
                  class="text-xs"
                >
                  {{ row.signals[key].reasons[0] }} · {{ row.signals[key].tradeDate }}
                </p>
              </TableCell>
            </TableRow>
            <TableRow v-if="!result.items.length">
              <TableCell
                :colspan="9"
                class="py-10 text-center text-muted-foreground"
              >
                {{ result.generatedAt ? '没有满足当前条件的股票；缺失信号不会被补为零分。' : '暂无正式共振快照，等待任务生成。' }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </template>
    <Dialog v-model:open="dialogOpen">
      <DialogContent class="sm:max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader><DialogTitle>{{ selected?.name }} · {{ selected?.code }}</DialogTitle><DialogDescription>目标 {{ result?.tradeDate }} · {{ result?.algorithmVersion }} · 各来源以独立日期为准。</DialogDescription></DialogHeader>
        <template v-if="selected">
          <p>共振 {{ selected.confluenceScore }} = 各维度贡献合计 / {{ selected.availableWeight }} × 100。正向 {{ selected.positiveSignalCount }} / 有效 {{ selected.availableSignalCount }}。</p>
          <section
            v-for="key in keys"
            :key="key"
            class="border-t pt-4 space-y-2"
          >
            <h3 class="font-semibold">
              {{ labels[key] }} · {{ states[selected.signals[key].status] }} · {{ selected.signals[key].score ?? '—' }}/{{ selected.signals[key].weight }}
            </h3>
            <p class="text-xs text-muted-foreground">
              来源 {{ selected.signals[key].sourceModule }} · 数据日期 {{ selected.signals[key].tradeDate ?? '缺失' }} · 源生成时间 {{ selected.signals[key].sourceGeneratedAt ? formatDateTime(selected.signals[key].sourceGeneratedAt!) : '缺失' }}
            </p>
            <dl
              v-if="selected.signals[key].status !== 'unavailable'"
              class="grid grid-cols-3 gap-3 text-sm"
            >
              <div
                v-for="[field, label] in fields[key]"
                :key="field"
              >
                <dt class="text-muted-foreground">
                  {{ label }}
                </dt><dd>{{ evidence(selected, key, field) }}</dd>
              </div>
            </dl>
            <div
              v-if="key === 'dragonTiger' && selected.signals[key].status !== 'unavailable'"
              class="text-sm space-y-1"
            >
              <p>最近记录（1D 与原生 3D 榜单分别展示，不累计）：</p>
              <p
                v-for="(record, index) in flowRecords(selected)"
                :key="index"
              >
                {{ record.tradeDate }} · {{ record.rangeDays }}D · 净额 {{ record.netInflow ?? '缺失' }} CNY · 机构 {{ record.institutionNetInflow ?? '缺失' }} · 游资 {{ record.hotMoneyNetInflow ?? '缺失' }}
              </p>
              <p
                v-for="(concept, index) in flowConcepts(selected)"
                :key="index"
              >
                概念 {{ concept.name }}：榜单分摊净额 {{ concept.netInflow ?? '缺失' }} CNY（仅解释）
              </p>
            </div>
            <ul class="list-disc pl-5 text-sm space-y-1">
              <li
                v-for="reason in selected.signals[key].reasons"
                :key="reason"
              >
                {{ reason }}
              </li>
            </ul>
          </section>
          <section class="border-t pt-4">
            <h3 class="font-semibold mb-2">
              Why Confluence
            </h3><ul class="list-disc pl-5 text-sm space-y-1">
              <li
                v-for="reason in selected.reasons"
                :key="reason"
              >
                {{ reason }}
              </li>
            </ul>
          </section>
        </template>
      </DialogContent>
    </Dialog>
  </div>
</template>

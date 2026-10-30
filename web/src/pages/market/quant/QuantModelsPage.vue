<script setup lang="ts">
import SortableTableHeader from '@/components/stocks/SortableTableHeader.vue';
import { useQuantTableSort } from '@/composables/useQuantTableSort';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { quantApi } from '@/api/quant';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHeader, TableRow } from '@/components/ui/table';
import { useQuantMarket } from '@/composables/useQuantMarket';
import type { ModelRun, QuantRelease, TrainingPreflight } from '@/types/quant';
import { MODEL_TARGET_COPY, isTrainableModelKey, primaryMetricValue, secondaryMetricValue, formatScore } from '@/utils/quant';

const { market, marketQuery } = useQuantMarket();
const runs = ref<ModelRun[]>([]), releases = ref<QuantRelease[]>([]);
const error = ref<ParsedApiError | null>(null);
const loading = ref(false), busy = ref(false), formOpen = ref(false), confirmOpen = ref(false);
const from = ref(`${new Date().getFullYear()-5}-01-01`), to = ref(new Date().toISOString().slice(0,10)), version = ref('');
const preflight = ref<TrainingPreflight | null>(null);
const cs = ref(''), ts = ref(''), reason = ref(''), message = ref('');
let generation = 0;
let actionGeneration = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
const active = computed(() => releases.value.find(x => x.active));
const payload = computed(() => ({market: market.value, dateFrom: from.value, dateTo: to.value, modelVersion: version.value}));
const canSubmit = computed(() => !!preflight.value && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(version.value));
const options = (key: string) => runs.value.filter(x => x.modelKey === key && ['candidate','production','retired'].includes(x.status)).map(x => ({value: String(x.id), label: `${x.modelVersion} · #${x.id}`}));
const labels: Record<string,string> = {draft:'准备中',training:'训练中',candidate:'待发布',production:'正式',retired:'已退役',failed:'失败'};
watch(payload, () => { preflight.value = null; });
async function load() {
  const token = ++generation; clearTimeout(timer); loading.value = true; error.value = null;
  try {
    const values = await Promise.all([quantApi.models(market.value),quantApi.releases(market.value)]);
    if(token !== generation) return;
    [runs.value,releases.value] = values;
    if(runs.value.some(x=>['draft','training'].includes(x.status))) timer = setTimeout(load, 10000);
  } catch(cause) { if(token === generation) error.value = getParsedApiError(cause); }
  finally { if(token === generation) loading.value = false; }
}
watch(market, () => {
  ++actionGeneration; busy.value=false;
  runs.value=[]; releases.value=[]; cs.value=''; ts.value=''; reason.value=''; message.value=''; formOpen.value=false; confirmOpen.value=false;
  version.value=`${market.value.toLowerCase()}-${Date.now()}`; void load();
}, {immediate:true});
onBeforeUnmount(()=>{ ++generation; ++actionGeneration; clearTimeout(timer); });
async function check() {
  const token=actionGeneration; const current = JSON.stringify(payload.value); busy.value=true; error.value=null;
  try { const result = await quantApi.preflight(payload.value); if(token === actionGeneration && current === JSON.stringify(payload.value)) preflight.value=result; }
  catch(cause) { if(token === actionGeneration && current === JSON.stringify(payload.value)) error.value=getParsedApiError(cause); }
  finally {if(token === actionGeneration) busy.value=false;}
}
async function train() {
  if(!canSubmit.value || busy.value) return;
  const token=actionGeneration; const current=market.value; busy.value=true; error.value=null;
  try { await quantApi.experiment(payload.value); if(token !== actionGeneration || current !== market.value) return; formOpen.value=false; message.value='训练实验已提交，将准备数据并训练两个模型。'; await load(); }
  catch(cause) {if(token === actionGeneration && current === market.value) error.value=getParsedApiError(cause);}
  finally {if(token === actionGeneration) busy.value=false;}
}
async function publish() {
  if(busy.value) return;
  const token=actionGeneration; const current=market.value; confirmOpen.value=false; busy.value=true; error.value=null;
  try { await quantApi.publishRelease(current,Number(cs.value),Number(ts.value),reason.value); if(token !== actionGeneration || current !== market.value) return; message.value='模型组已发布，下一轮计算将使用新模型组。'; await load(); }
  catch(cause) {if(token === actionGeneration && current === market.value) error.value=getParsedApiError(cause);}
  finally {if(token === actionGeneration) busy.value=false;}
}
function rollback(item: QuantRelease) {cs.value=String(item.crossSectionId); ts.value=String(item.timeSeriesId); reason.value=`回滚到模型组 #${item.id}`; confirmOpen.value=true;}
function secondary(row: ModelRun) { const v=secondaryMetricValue(row.modelKey,row.metrics); return row.modelKey==='time_series_lgbm' && v!=null ? `${(v*100).toFixed(1)}%` : formatScore(v); }
const { sortKey, direction, toggle, sorted: sortedRuns } = useQuantTableSort(
  () => runs.value,
  (row, key) => key === 'primary' ? primaryMetricValue(row.modelKey,row.metrics)
    : key === 'secondary' ? secondaryMetricValue(row.modelKey,row.metrics)
    : key === 'cutoff' ? row.metrics.finalTrainingEnd : row[key as keyof ModelRun], 'id', 'desc');
</script>
<template>
  <div class="space-y-4">
    <PageHeader
      variant="section"
      title="模型管理"
      description="训练与每日推理独立；审核两个候选模型后成组发布。"
    >
      <template #actions>
        <LoadingButton
          :loading="loading"
          variant="outline"
          @click="load"
        >
          刷新
        </LoadingButton><Button
          :disabled="busy"
          @click="formOpen=!formOpen"
        >
          创建训练实验
        </Button>
      </template>
    </PageHeader>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <p
      v-if="message"
      role="status"
      class="text-sm"
    >
      {{ message }}
    </p>
    <Card>
      <CardHeader><CardTitle>当前正式模型组 {{ active ? `#${active.id}` : '尚未发布' }}</CardTitle></CardHeader><CardContent class="text-sm">
        横截面 #{{ active?.crossSectionId ?? '—' }} · 时间序列 #{{ active?.timeSeriesId ?? '—' }}
      </CardContent>
    </Card>
    <Card v-if="formOpen">
      <CardHeader><CardTitle>创建训练实验</CardTitle></CardHeader>
      <CardContent class="space-y-4">
        <div class="grid gap-3 sm:grid-cols-3">
          <AppDatePicker
            v-model="from"
            label="历史开始日期"
          /><AppDatePicker
            v-model="to"
            label="历史结束日期"
          /><FieldInput
            v-model="version"
            label="实验版本"
            maxlength="96"
          />
        </div>
        <p class="text-sm text-muted-foreground">
          使用多年历史，完成特征预热后按3年训练、3个月验证、3个月测试滚动评估。系统自动准备训练输入。
        </p>
        <p
          v-if="preflight"
          role="status"
          class="text-sm"
        >
          有效交易日 {{ preflight.sessions }} · 有效股票 {{ preflight.eligibleCount }}/{{ preflight.memberCount }} · 标签截止 {{ preflight.labelCutoff }}。{{ preflight.warning }}
        </p>
        <div class="flex gap-2">
          <LoadingButton
            :loading="busy"
            :disabled="!version || !from || !to"
            variant="outline"
            @click="check"
          >
            检查训练数据
          </LoadingButton><LoadingButton
            :loading="busy"
            :disabled="!canSubmit"
            @click="train"
          >
            提交双模型训练
          </LoadingButton>
        </div>
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle>训练记录与评估</CardTitle></CardHeader><CardContent>
        <p
          v-if="!runs.length && !loading && !error"
          class="text-sm"
        >
          暂无训练记录。
        </p>
        <Table v-else>
          <TableHeader>
            <TableRow>
              <SortableTableHeader
                label="模型 / 版本"
                scope="quant"
                :active="sortKey === 'modelVersion'"
                :direction="direction"
                @sort="toggle('modelVersion')"
              />
              <SortableTableHeader
                label="状态"
                scope="quant"
                :active="sortKey === 'status'"
                :direction="direction"
                @sort="toggle('status')"
              />
              <SortableTableHeader
                label="主要评估"
                scope="quant"
                :active="sortKey === 'primary'"
                :direction="direction"
                @sort="toggle('primary')"
              />
              <SortableTableHeader
                label="辅助评估"
                scope="quant"
                :active="sortKey === 'secondary'"
                :direction="direction"
                @sort="toggle('secondary')"
              />
              <SortableTableHeader
                label="实际拟合截止"
                scope="quant"
                :active="sortKey === 'cutoff'"
                :direction="direction"
                @sort="toggle('cutoff')"
              />
              <SortableTableHeader
                label="进度"
                scope="quant"
                :active="sortKey === 'progress'"
                :direction="direction"
                @sort="toggle('progress')"
              />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow
              v-for="row in sortedRuns"
              :key="row.id"
            >
              <TableCell>
                <RouterLink
                  :to="{path:`/research/quant/models/${row.id}`,query:marketQuery()}"
                  class="underline"
                >
                  {{ isTrainableModelKey(row.modelKey) ? MODEL_TARGET_COPY[row.modelKey].shortName : row.modelKey }} · {{ row.modelVersion }} · #{{ row.id }}
                </RouterLink>
              </TableCell>
              <TableCell>{{ labels[row.status] ?? row.status }}</TableCell><TableCell>{{ row.modelKey==='time_series_lgbm' ? 'AUC' : 'Daily Rank IC' }} {{ formatScore(primaryMetricValue(row.modelKey,row.metrics)) }}</TableCell><TableCell>{{ row.modelKey==='time_series_lgbm' ? '方向命中率' : 'Top10超额（百分点）' }} {{ secondary(row) }}</TableCell><TableCell>{{ row.metrics.finalTrainingEnd ?? '—' }}</TableCell><TableCell>{{ row.progress }}%</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle>发布模型组</CardTitle></CardHeader><CardContent class="space-y-3">
        <div class="grid gap-3 sm:grid-cols-2">
          <FieldSelect
            v-model="cs"
            label="横截面模型"
            :options="options('cross_section_lgbm')"
          /><FieldSelect
            v-model="ts"
            label="时间序列模型"
            :options="options('time_series_lgbm')"
          />
        </div>
        <FieldInput
          v-model="reason"
          label="审核结论 / 发布原因"
        /><Button
          :disabled="busy || !cs || !ts || reason.trim().length<3"
          @click="confirmOpen=true"
        >
          发布选定模型组
        </Button>
        <p class="text-xs text-muted-foreground">
          评估为历史滚动验证结果。发布会整体替换当前模型组。
        </p>
      </CardContent>
    </Card>
    <Card v-if="releases.length">
      <CardHeader><CardTitle>发布历史</CardTitle></CardHeader><CardContent class="space-y-2">
        <div
          v-for="release in releases"
          :key="release.id"
          class="flex flex-wrap items-center justify-between gap-2 text-sm"
        >
          <span>#{{ release.id }} · 横截面 #{{ release.crossSectionId }} / 时间序列 #{{ release.timeSeriesId }} · {{ release.reason }}</span><Button
            v-if="!release.active"
            :disabled="busy"
            variant="outline"
            size="sm"
            @click="rollback(release)"
          >
            回滚到此组
          </Button>
        </div>
      </CardContent>
    </Card>
    <AppConfirmDialog
      :open="confirmOpen"
      title="发布模型组"
      :description="`将使用横截面 #${cs} 和时间序列 #${ts}，替换当前正式模型组。`"
      confirm-text="确认发布"
      @update:open="confirmOpen=$event"
      @confirm="publish"
    />
  </div>
</template>

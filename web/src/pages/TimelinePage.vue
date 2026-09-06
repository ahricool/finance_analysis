<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { ArrowUpRight, Bell, FileText, Globe2, PenLine, Plus } from 'lucide-vue-next';
import { timelineApi, type Actionability, type Category, type Importance, type TimelineItem, type TimelineQuery, type TimelineSummary } from '@/api/timeline';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import LoadingButton from '@/components/app/LoadingButton.vue';
import { Button } from '@/components/ui/button';
import { Dialog, DialogDescription, DialogHeader, DialogScrollContent, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { useTimezoneStore } from '@/stores/timezoneStore';
import { formatDateTimeInDisplayTimezone, getTodayInDisplayTimezone } from '@/utils/format';
import { renderMarkdownToHtml } from '@/utils/renderMarkdown';

const { displayTimezone } = storeToRefs(useTimezoneStore());
const market = ref('');
const category = ref<Category | ''>('');
const importance = ref<Importance | ''>('');
const actionability = ref<Actionability | ''>('');
const date = ref('');
const items = ref<TimelineItem[]>([]);
const summaries = ref<TimelineSummary[]>([]);
const total = ref(0);
const page = ref(1);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const detail = ref<TimelineItem | null>(null);
const noteOpen = ref(false);
const saving = ref(false);
const editingId = ref<number>();
const form = reactive({ title: '', summary: '', content: '', market: '' as '' | 'CN' | 'US', importance: 'normal' as Importance, actionability: 'none' as Actionability, symbols: '' });
const noteError = ref<ParsedApiError | null>(null);
const noteEventTime = ref('');
const categories = [{ value: '', label: '全部' }, { value: 'event', label: '财经事件' }, { value: 'news', label: '新闻' }, { value: 'analysis', label: '市场分析' }, { value: 'note', label: '笔记' }] as const;
const categoryNames: Record<Category, string> = { event: '财经事件', news: '新闻', analysis: '市场分析', note: '笔记' };
const importanceNames: Record<Importance, string> = { low: 'Low', normal: 'Normal', high: 'High', critical: 'Critical' };
const actionNames: Record<Actionability, string> = { none: '仅供了解', watch: '关注', consider: '考虑', action_required: '需要行动' };
const icons = { event: Globe2, news: Bell, analysis: FileText, note: PenLine };
const query = computed<TimelineQuery>(() => ({ ...(date.value ? { date: date.value } : {}), market: market.value || undefined, category: category.value || undefined, importance: importance.value || undefined, actionability: actionability.value || undefined }));
const todaySummary = computed(() => summaries.value.find(item => item.date === getTodayInDisplayTimezone()));
let requestId = 0;
async function load(append = false) {
  const id = ++requestId;
  loading.value = true;
  error.value = null;
  const requestedPage = append ? page.value + 1 : 1;
  try {
    const [response, summary] = await Promise.all([timelineApi.list({ ...query.value, page: requestedPage, limit: 20 }), timelineApi.summary(query.value)]);
    if (id !== requestId) return;
    items.value = append ? [...items.value, ...response.items] : response.items;
    total.value = response.total;
    summaries.value = summary;
    page.value = requestedPage;
  } catch (err) { if (id === requestId) error.value = getParsedApiError(err); }
  finally { if (id === requestId) loading.value = false; }
}
watch([query, displayTimezone], () => { items.value = []; void load(); }, { immediate: true });
function dayOf(item: TimelineItem) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: displayTimezone.value, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(item.eventTime));
}
function timeOf(item: TimelineItem) {
  if (item.detailPayload.allDay) return '全天';
  return new Intl.DateTimeFormat('zh-CN', { timeZone: displayTimezone.value, hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(item.eventTime));
}
function openNote(item?: TimelineItem) {
  editingId.value = item?.sourceId;
  noteEventTime.value = item?.eventTime || new Date().toISOString();
  Object.assign(form, { title: item?.title || '', summary: item?.summary || '', content: String(item?.detailPayload.content || ''), market: item?.market || '', importance: item?.importance || 'normal', actionability: item?.actionability || 'none', symbols: item?.relatedSymbols.join(', ') || '' });
  noteError.value = null;
  detail.value = null;
  noteOpen.value = true;
}
async function saveNote() {
  saving.value = true;
  noteError.value = null;
  try {
    await timelineApi.saveNote({ title: form.title, summary: form.summary, content: form.content, market: form.market || null, importance: form.importance, actionability: form.actionability, event_time: noteEventTime.value, related_symbols: form.symbols.split(/[,，\s]+/).filter(Boolean) }, editingId.value);
    noteOpen.value = false;
    await load();
  } catch (err) { noteError.value = getParsedApiError(err); }
  finally { saving.value = false; }
}
async function deleteNote() {
  if (editingId.value === undefined) return;
  saving.value = true;
  try { await timelineApi.deleteNote(editingId.value); noteOpen.value = false; await load(); }
  catch (err) { noteError.value = getParsedApiError(err); }
  finally { saving.value = false; }
}
const newsFields = [
  ['importanceScore', '重要性评分'], ['importanceReason', '重要性依据'], ['eventType', '事件类型'],
  ['timeSensitivity', '时效性'], ['importanceConfidence', '重要性置信度'], ['impact', '影响方向'],
  ['impactScore', '影响评分'], ['impactReason', '影响依据'], ['impactConfidence', '影响置信度'],
  ['watchPoints', '观察要点'], ['riskNotes', '风险提示'],
] as const;
function fieldText(value: unknown) { return Array.isArray(value) ? value.join('\n') : String(value ?? '—'); }
function safeUrl(value: unknown) { return typeof value === 'string' && /^https?:\/\//i.test(value) ? value : undefined; }
</script>

<template>
  <div
    class="mx-auto w-full max-w-3xl border-x border-border min-h-screen"
    data-testid="investment-timeline"
  >
    <header class="border-b border-border px-4 py-5 sm:px-6">
      <div class="flex items-start justify-between gap-3">
        <div>
          <p class="text-xs tracking-widest text-muted-foreground">
            INVESTMENT TIMELINE
          </p><h1 class="mt-1 text-2xl font-semibold tracking-tight">
            投资时间线
          </h1><p class="mt-2 text-sm text-muted-foreground">
            按时间汇总值得关注的投资信息。
          </p>
        </div>
        <Button
          data-testid="add-note"
          @click="openNote()"
        >
          <Plus class="size-4" />新增笔记
        </Button>
      </div>
      <p
        v-if="todaySummary"
        class="mt-4 text-xs text-muted-foreground"
      >
        今天 {{ todaySummary.total }} 条 · {{ todaySummary.critical }} 条 Critical · {{ todaySummary.high }} 条 High
      </p>
    </header>
    <div class="border-b border-border bg-background/95 px-4 py-3 space-y-3 sm:px-6">
      <div
        class="flex flex-wrap items-center gap-2"
        aria-label="市场筛选"
      >
        <button
          v-for="option in [{ value: '', label: '全部市场' }, { value: 'CN', label: 'A股' }, { value: 'US', label: '美股' }]"
          :key="option.value"
          class="rounded-full px-3 py-1.5 text-sm transition-colors hover:bg-muted"
          :class="market === option.value ? 'bg-foreground text-background font-medium' : 'text-muted-foreground'"
          :aria-pressed="market === option.value"
          @click="market = option.value"
        >
          {{ option.label }}
        </button>
      </div>
      <div
        class="flex gap-1 overflow-x-auto"
        aria-label="内容类型筛选"
      >
        <button
          v-for="option in categories"
          :key="option.value"
          class="shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm"
          :class="category === option.value ? 'border-primary font-semibold' : 'border-transparent text-muted-foreground'"
          :aria-pressed="category === option.value"
          @click="category = option.value"
        >
          {{ option.label }}
        </button>
      </div>
      <div class="flex flex-wrap items-center gap-2 text-xs">
        <select
          v-model="importance"
          aria-label="重要度"
          class="rounded-md border border-input bg-background p-2"
        >
          <option value="">
            全部重要度
          </option><option value="critical">
            Critical
          </option><option value="high">
            High
          </option>
        </select>
        <select
          v-model="actionability"
          aria-label="行动等级"
          class="rounded-md border border-input bg-background p-2"
        >
          <option value="">
            全部行动
          </option><option value="action_required">
            需要行动
          </option><option value="consider">
            考虑
          </option><option value="watch">
            关注
          </option>
        </select>
        <AppDatePicker
          v-model="date"
          placeholder="筛选日期"
        />
        <button
          v-if="date"
          class="text-muted-foreground hover:text-foreground"
          @click="date = ''"
        >
          恢复时间流
        </button>
        <span class="ml-auto text-muted-foreground">{{ displayTimezone === 'Asia/Shanghai' ? '北京时间' : '美东时间' }}</span>
      </div>
    </div>
    <ApiErrorAlert
      v-if="error"
      :error="error"
      class="m-4"
    />
    <div
      v-if="loading && !items.length"
      class="space-y-6 p-6"
      aria-label="正在加载"
    >
      <div
        v-for="i in 4"
        :key="i"
        class="h-24 animate-pulse rounded bg-muted"
      />
    </div>
    <div
      v-else-if="!items.length && !error"
      class="px-6 py-16 text-center"
    >
      <p class="font-medium">
        暂无匹配的信息
      </p><p class="mt-2 text-sm text-muted-foreground">
        试试其他日期或调整筛选条件。
      </p>
    </div>
    <template
      v-for="(item, index) in items"
      :key="item.id"
    >
      <div
        v-if="index === 0 || dayOf(items[index - 1]!) !== dayOf(item)"
        class="border-b border-border bg-muted/30 px-5 py-2 text-xs font-medium text-muted-foreground"
      >
        {{ dayOf(item) }}
      </div>
      <article
        class="group border-b border-border px-4 py-5 transition-colors hover:bg-muted/30 sm:px-6"
        data-testid="timeline-item"
      >
        <button
          class="flex w-full gap-3 text-left"
          :aria-label="`查看${item.title}`"
          @click="detail = item"
        >
          <span class="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground"><component
            :is="icons[item.category]"
            class="size-4"
          /></span>
          <span class="min-w-0 flex-1">
            <span class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground"><span class="font-semibold text-foreground">{{ categoryNames[item.category] }}</span><span v-if="item.market">{{ item.market === 'CN' ? 'A股' : item.market === 'US' ? '美股' : item.market }}</span><span>·</span><time :datetime="item.eventTime">{{ timeOf(item) }}</time></span>
            <span class="mt-2 block break-words text-base font-semibold leading-relaxed">{{ item.title }}</span>
            <span
              v-if="item.summary"
              class="mt-1 line-clamp-2 text-sm leading-relaxed text-muted-foreground"
            >{{ item.summary }}</span>
            <span class="mt-3 flex flex-wrap items-center gap-2 text-xs">
              <span
                class="rounded px-1.5 py-0.5 font-medium"
                :class="item.importance === 'critical' ? 'bg-destructive/10 text-destructive' : item.importance === 'high' ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400' : 'bg-muted text-muted-foreground'"
              >{{ item.category === 'news' ? `${item.importanceScore}/10` : importanceNames[item.importance] }}</span>
              <span class="text-muted-foreground">{{ actionNames[item.actionability] }}</span>
              <span
                v-if="item.impact"
                :class="item.impact === 'bullish' ? 'text-market-up' : item.impact === 'bearish' ? 'text-market-down' : 'text-muted-foreground'"
              >{{ item.impact }} {{ item.impactScore !== null && item.impactScore > 0 ? '+' : '' }}{{ item.impactScore }}</span>
              <span
                v-for="symbol in item.relatedSymbols.slice(0, 6)"
                :key="symbol"
                class="font-medium text-foreground"
              >${{ symbol }}</span>
            </span>
          </span>
          <ArrowUpRight class="mt-1 size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
        </button>
      </article>
    </template>
    <div
      v-if="items.length < total"
      class="p-5 text-center"
    >
      <LoadingButton
        variant="ghost"
        :loading="loading"
        @click="load(true)"
      >
        加载更多
      </LoadingButton>
    </div>
    <p
      v-else-if="items.length"
      class="p-6 text-center text-xs text-muted-foreground"
    >
      已显示当前范围内的 {{ total }} 条信息
    </p>

    <Dialog
      :open="!!detail"
      @update:open="value => { if (!value) detail = null; }"
    >
      <DialogScrollContent class="sm:max-w-3xl">
        <template v-if="detail">
          <DialogHeader><DialogTitle>{{ detail.title }}</DialogTitle><DialogDescription>{{ categoryNames[detail.category] }} · {{ formatDateTimeInDisplayTimezone(detail.eventTime) }} · {{ importanceNames[detail.importance] }} · {{ actionNames[detail.actionability] }}</DialogDescription></DialogHeader>
          <p
            v-if="detail.relatedSymbols.length"
            class="text-sm font-medium"
          >
            {{ detail.relatedSymbols.join(' · ') }}
          </p>
          <template v-if="detail.category === 'news'">
            <p class="text-sm text-muted-foreground">
              {{ detail.detailPayload.source }} · {{ detail.detailPayload.publishedAt ? formatDateTimeInDisplayTimezone(String(detail.detailPayload.publishedAt)) : '发布时间未提供' }}
            </p>
            <a
              v-if="safeUrl(detail.detailPayload.url)"
              :href="safeUrl(detail.detailPayload.url)"
              target="_blank"
              rel="noopener noreferrer"
              class="text-sm underline"
            >阅读原文 ↗</a>
            <dl class="space-y-4">
              <div
                v-for="[key, label] in newsFields"
                :key="key"
              >
                <dt class="text-xs text-muted-foreground">
                  {{ label }}
                </dt><dd class="mt-1 whitespace-pre-line text-sm leading-relaxed">
                  {{ fieldText(detail.detailPayload[key]) }}
                </dd>
              </div>
            </dl>
          </template>
          <div
            v-else
            class="prose prose-sm max-w-none break-words dark:prose-invert"
            v-html="renderMarkdownToHtml(String(detail.detailPayload.content || ''))"
          />
          <Button
            v-if="detail.category === 'note'"
            variant="outline"
            @click="openNote(detail)"
          >
            编辑笔记
          </Button>
        </template>
      </DialogScrollContent>
    </Dialog>
    <Dialog v-model:open="noteOpen">
      <DialogScrollContent>
        <DialogHeader><DialogTitle>{{ editingId ? '编辑笔记' : '新增笔记' }}</DialogTitle><DialogDescription>记下投资判断、观察重点与后续行动。</DialogDescription></DialogHeader>
        <form
          class="space-y-4"
          @submit.prevent="saveNote"
        >
          <label class="block space-y-1 text-sm"><span>标题</span><Input
            v-model="form.title"
            required
            maxlength="300"
          /></label>
          <label class="block space-y-1 text-sm"><span>短摘要</span><Input
            v-model="form.summary"
            maxlength="500"
          /></label>
          <label class="block space-y-1 text-sm"><span>笔记内容</span><Textarea
            v-model="form.content"
            :rows="7"
          /></label>
          <label class="block space-y-1 text-sm"><span>相关标的（逗号分隔）</span><Input v-model="form.symbols" /></label>
          <div class="flex flex-wrap gap-2">
            <select
              v-model="form.market"
              aria-label="笔记市场"
              class="rounded border bg-background p-2 text-sm"
            >
              <option value="">
                不限市场
              </option><option value="CN">
                A股
              </option><option value="US">
                美股
              </option>
            </select>
            <select
              v-model="form.importance"
              aria-label="笔记重要度"
              class="rounded border bg-background p-2 text-sm"
            >
              <option
                v-for="(label, value) in importanceNames"
                :key="value"
                :value="value"
              >
                {{ label }}
              </option>
            </select>
            <select
              v-model="form.actionability"
              aria-label="笔记行动等级"
              class="rounded border bg-background p-2 text-sm"
            >
              <option
                v-for="(label, value) in actionNames"
                :key="value"
                :value="value"
              >
                {{ label }}
              </option>
            </select>
          </div>
          <ApiErrorAlert
            v-if="noteError"
            :error="noteError"
          />
          <div class="flex justify-end gap-2">
            <LoadingButton
              v-if="editingId"
              type="button"
              variant="destructive"
              :loading="saving"
              @click="deleteNote"
            >
              删除笔记
            </LoadingButton><LoadingButton
              type="submit"
              :loading="saving"
              :disabled="!form.title.trim()"
            >
              保存笔记
            </LoadingButton>
          </div>
        </form>
      </DialogScrollContent>
    </Dialog>
  </div>
</template>

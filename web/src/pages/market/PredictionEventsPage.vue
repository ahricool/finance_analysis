<script setup lang="ts">
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { predictionApi, type PredictionTag, type EventPage } from '@/api/predictionMarkets';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { useAuth } from '@/composables/useAuth';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppPagination from '@/components/app/AppPagination.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { Button } from '@/components/ui/button';
import PredictionEventCard from '@/components/prediction-markets/PredictionEventCard.vue';
const PredictionAdmin = defineAsyncComponent(() => import('@/components/prediction-markets/PredictionAdmin.vue'));
const { currentUser } = useAuth();
const tags = ref<PredictionTag[]>([]); const selected = ref<string[]>([]); const keyword = ref(''); const search = ref(''); const state = ref('open'); const sort = ref('updated'); const page = ref(1);
const data = ref<EventPage>(); const error = ref<ParsedApiError | null>(null); const loading = ref(false); const admin = ref(false);
let generation = 0; let controller: AbortController | undefined;
const tagController = new AbortController();
async function loadTags() { try { const result = await predictionApi.tags(tagController.signal); if (!tagController.signal.aborted) tags.value = result.items; } catch (cause) { if (!tagController.signal.aborted) error.value = getParsedApiError(cause); } }
async function load() {
  controller?.abort(); controller = new AbortController(); const token = ++generation;
  data.value = undefined; error.value = null; loading.value = true;
  try { const result = await predictionApi.events({ page: page.value, pageSize: 10, keyword: search.value, tagIds: selected.value, closed: state.value === 'closed', sort: sort.value }, controller.signal); if (token === generation) data.value = result; }
  catch (cause) { if (token === generation && !controller.signal.aborted) error.value = getParsedApiError(cause); }
  finally { if (token === generation) loading.value = false; }
}
function toggle(id: string) { selected.value = selected.value.includes(id) ? selected.value.filter(t => t !== id) : [...selected.value, id]; }
watch([selected, state, sort, search], () => { if (page.value !== 1) page.value = 1; else void load(); });
watch(page, load);
onMounted(() => { void loadTags(); void load(); });
onBeforeUnmount(() => { ++generation; controller?.abort(); tagController.abort(); });
function refresh() { selected.value = []; void loadTags(); void load(); }
</script>
<template>
  <div
    class="space-y-5"
    data-testid="prediction-events-page"
  >
    <PageHeader
      title="事件预测"
      en="Prediction Events"
      description="按规则筛选官方话题，按需查看选项、隐含概率及历史变化。"
    />
    <div
      class="flex flex-wrap gap-2"
      aria-label="官方标签（多个标签取并集）"
    >
      <Button
        :variant="selected.length ? 'outline' : 'default'"
        size="sm"
        @click="selected = []"
      >
        全部允许标签
      </Button>
      <Button
        v-for="tag in tags"
        :key="tag.tagId"
        :variant="selected.includes(tag.tagId) ? 'default' : 'outline'"
        :aria-pressed="selected.includes(tag.tagId)"
        size="sm"
        @click="toggle(tag.tagId)"
      >
        {{ tag.label }} · {{ tag.eventCount }}
      </Button>
    </div>
    <form
      class="flex flex-wrap items-end gap-3"
      @submit.prevent="search = keyword.trim()"
    >
      <FieldInput
        v-model="keyword"
        label="关键词"
        class="min-w-0 flex-1"
      /><Button type="submit">
        搜索
      </Button>
      <FieldSelect
        v-model="state"
        label="话题状态"
        class="w-36"
        :options="[{ value: 'open', label: '未关闭' }, { value: 'closed', label: '已关闭历史' }]"
      />
      <FieldSelect
        v-model="sort"
        label="全局排序"
        class="w-40"
        :options="[{ value: 'updated', label: '目录更新时间' }, { value: 'deadline', label: '截止时间' }, { value: 'title', label: '标题' }]"
      />
      <Button
        variant="outline"
        type="button"
        :disabled="loading"
        @click="load"
      >
        刷新
      </Button>
    </form>
    <Button
      v-if="currentUser?.role === 'admin'"
      variant="outline"
      @click="admin = !admin"
    >
      {{ admin ? '收起管理' : '共享配置管理' }}
    </Button>
    <PredictionAdmin
      v-if="admin && currentUser?.role === 'admin'"
      @changed="refresh"
    />
    <p
      v-if="loading"
      role="status"
    >
      加载话题目录…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
      action-label="重试"
      @action="load"
    />
    <p v-else-if="data?.status === 'disabled'">
      事件预测功能未启用。
    </p>
    <p v-else-if="!data?.items.length">
      {{ data?.status === 'not_synced' ? '官方目录尚未同步。' : '暂无符合筛选条件的话题。' }}
    </p>
    <p
      v-if="data?.total"
      class="text-sm text-muted-foreground"
    >
      共 {{ data.total }} 个话题 · 标签为 OR 并集 · 仅当前页读取动态选项
    </p>
    <PredictionEventCard
      v-for="event in data?.items"
      :key="event.eventId"
      :event="event"
    />
    <AppPagination
      :current-page="page"
      :total-pages="Math.ceil((data?.total ?? 0) / 10)"
      @page-change="page = $event"
    />
  </div>
</template>

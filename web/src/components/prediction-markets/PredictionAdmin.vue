<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { predictionApi, type PredictionTag, type EventPage } from '@/api/predictionMarkets';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppPagination from '@/components/app/AppPagination.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { Button } from '@/components/ui/button';
const emit = defineEmits<{ changed: [] }>();
const tags = ref<PredictionTag[]>([]); const events = ref<EventPage>(); const search = ref(''); const keyword = ref(''); const slug = ref(''); const page = ref(1);
const eventId = ref(''); const symbol = ref(''); const reason = ref(''); const action = ref('add');
const error = ref<ParsedApiError | null>(null); const message = ref(''); const busy = ref(false);
const controller = new AbortController();
const tagPage = ref(1);
const filteredTags = computed(() => tags.value.filter(t => `${t.label} ${t.slug}`.toLowerCase().includes(search.value.toLowerCase())));
const visibleTags = computed(() => filteredTags.value.slice((tagPage.value - 1) * 50, tagPage.value * 50));
watch(search, () => { tagPage.value = 1; });
async function load() { const [t, e] = await Promise.all([predictionApi.adminTags(controller.signal), predictionApi.adminEvents(page.value, keyword.value, controller.signal)]); if (!controller.signal.aborted) { tags.value = t.items; events.value = e; } }
async function perform(fn: () => Promise<unknown>) {
  busy.value = true; error.value = null;
  try { await fn(); await load(); emit('changed'); }
  catch (cause) { if (!controller.signal.aborted) error.value = getParsedApiError(cause); }
  finally { busy.value = false; }
}
async function run(job: 'catalog' | 'matching', value?: string) {
  await perform(async () => { const result = await predictionApi.run(job, value); message.value = `已提交任务 ${result.taskId}，请在任务中心查看结果。`; });
}
onMounted(() => { void perform(async () => {}); });
onBeforeUnmount(() => controller.abort());
</script>
<template>
  <section
    class="space-y-4 rounded-xl border p-4"
    data-testid="prediction-admin"
  >
    <p class="font-medium">
      共享配置管理 · 修改影响所有用户
    </p>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
    />
    <p
      v-if="message"
      role="status"
      class="break-all text-sm"
    >
      {{ message }}
    </p>
    <div class="flex flex-wrap items-end gap-2">
      <FieldInput
        v-model="slug"
        label="手工导入官方事件 URL / slug"
        class="min-w-0 flex-1"
      />
      <Button
        :disabled="busy || !slug"
        @click="run('catalog', slug)"
      >
        导入
      </Button>
      <Button
        variant="outline"
        :disabled="busy"
        @click="run('catalog')"
      >
        同步目录
      </Button>
      <Button
        variant="outline"
        :disabled="busy"
        @click="run('matching')"
      >
        重试匹配
      </Button>
    </div>
    <FieldInput
      v-model="search"
      label="全量官方标签搜索"
    />
    <div class="max-h-80 space-y-2 overflow-y-auto">
      <div
        v-for="tag in visibleTags"
        :key="tag.tagId"
        data-testid="prediction-admin-tag"
        class="flex flex-wrap items-center gap-2 rounded-md border p-2 text-sm"
      >
        <span class="min-w-0 flex-1 break-words">{{ tag.label }} / {{ tag.slug }} · 规则：{{ tag.ruleGroup }} · {{ tag.visible ? '显示' : '隐藏' }} · {{ tag.manualVisible == null ? '自动' : '人工覆盖' }}</span>
        <Button
          size="sm"
          variant="outline"
          :disabled="busy"
          @click="perform(() => predictionApi.setTag(tag.tagId, !tag.visible))"
        >
          {{ tag.visible ? '隐藏' : '显示' }}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          :disabled="busy"
          @click="perform(() => predictionApi.setTag(tag.tagId, null))"
        >
          恢复规则
        </Button>
      </div>
    </div>
    <AppPagination
      :current-page="tagPage"
      :total-pages="Math.ceil(filteredTags.length / 50)"
      @page-change="tagPage = $event"
    />
    <div class="flex items-end gap-2">
      <FieldInput
        v-model="keyword"
        label="管理话题（包含已排除）"
        class="min-w-0 flex-1"
      /><Button
        variant="outline"
        :disabled="busy"
        @click="page = 1; perform(async () => {})"
      >
        搜索
      </Button>
    </div>
    <div
      v-for="event in events?.items"
      :key="event.eventId"
      class="space-y-2 rounded-md border p-3 text-sm"
    >
      <p class="break-words">
        {{ event.eventId }} · {{ event.title }}
      </p>
      <p>规则：{{ event.ruleReason }} · {{ event.manualRetained == null ? '自动' : '人工覆盖' }} · {{ event.retained ? '保留' : '排除' }}</p>
      <div class="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          :disabled="busy"
          @click="perform(() => predictionApi.setEvent(event.eventId, !event.retained))"
        >
          {{ event.retained ? '排除' : '纳入' }}
        </Button><Button
          size="sm"
          variant="ghost"
          :disabled="busy"
          @click="perform(() => predictionApi.setEvent(event.eventId, null))"
        >
          恢复规则
        </Button><Button
          size="sm"
          variant="ghost"
          @click="eventId = event.eventId"
        >
          纠正关联
        </Button>
      </div>
      <p
        v-for="link in event.links"
        :key="link.symbol"
      >
        {{ link.symbol }} · {{ link.blocked ? '已屏蔽' : link.source }} · {{ link.reason }}
      </p>
    </div>
    <AppPagination
      :current-page="page"
      :total-pages="Math.ceil((events?.total ?? 0) / 10)"
      @page-change="page = $event; perform(async () => {})"
    />
    <div class="grid gap-3 sm:grid-cols-2">
      <FieldInput
        v-model="eventId"
        label="事件 ID"
      /><FieldInput
        v-model="symbol"
        label="规范证券代码（支持已有港股）"
        placeholder="NVDA.US"
      />
      <FieldSelect
        v-model="action"
        label="关联纠错"
        :options="[{ value: 'add', label: '人工添加' }, { value: 'block', label: '人工屏蔽' }, { value: 'restore', label: '恢复自动匹配' }]"
      />
      <FieldInput
        v-model="reason"
        label="中文关联理由"
      />
    </div>
    <Button
      :disabled="busy || !eventId || !symbol || !reason.trim()"
      @click="perform(() => predictionApi.setLink(eventId, symbol, action, reason))"
    >
      保存共享关联
    </Button>
  </section>
</template>

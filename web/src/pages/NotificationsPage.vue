<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import { notificationsApi, type NotificationDetail, type NotificationPreview, type NotificationQuery } from '@/api/notifications';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import PageHeader from '@/components/layout/PageHeader.vue';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppDateTimePicker from '@/components/app/AppDateTimePicker.vue';
import AppPagination from '@/components/app/AppPagination.vue';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Dialog, DialogDescription, DialogHeader, DialogScrollContent, DialogTitle } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import { renderMarkdownToHtml } from '@/utils/renderMarkdown';

const keyword = ref('');
const routeType = ref('all');
const severity = ref('all');
const startTime = ref('');
const endTime = ref('');
const items = ref<NotificationPreview[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const detail = ref<NotificationDetail | null>(null);
const detailError = ref<ParsedApiError | null>(null);
const detailLoading = ref(false);
const open = ref(false);
const types: Record<string, string> = { report: '报告', alert: '提醒', system_error: '系统错误' };
const levels: Record<string, string> = { debug: '调试', info: '信息', warning: '警告', error: '错误', critical: '严重' };
const totalPages = computed(() => Math.ceil(total.value / pageSize));
const invalidRange = computed(() => !!startTime.value && !!endTime.value && startTime.value > endTime.value);
let listRequest = 0;
let detailRequest = 0;
let applied: NotificationQuery = {};

async function load(targetPage = 1) {
  const request = ++listRequest;
  loading.value = true;
  error.value = null;
  try {
    const result = await notificationsApi.list({ ...applied, page: targetPage, page_size: pageSize });
    if (request !== listRequest) return;
    items.value = result.items;
    total.value = result.total;
    page.value = result.page;
  } catch (cause) {
    if (request === listRequest) error.value = getParsedApiError(cause);
  } finally {
    if (request === listRequest) loading.value = false;
  }
}
function search() {
  if (invalidRange.value) return;
  applied = {
    keyword: keyword.value.trim() || undefined,
    route_type: routeType.value === 'all' ? undefined : routeType.value,
    severity: severity.value === 'all' ? undefined : severity.value,
    start_time: startTime.value ? new Date(startTime.value).toISOString() : undefined,
    end_time: endTime.value ? new Date(endTime.value).toISOString() : undefined,
  };
  void load();
}
function reset() {
  keyword.value = ''; routeType.value = 'all'; severity.value = 'all';
  startTime.value = ''; endTime.value = '';
  search();
}
async function showDetail(id: number) {
  const request = ++detailRequest;
  detail.value = null;
  detailError.value = null;
  open.value = true;
  detailLoading.value = true;
  try {
    const result = await notificationsApi.detail(id);
    if (request === detailRequest) detail.value = result;
  } catch (cause) {
    if (request === detailRequest) detailError.value = getParsedApiError(cause);
  } finally {
    if (request === detailRequest) detailLoading.value = false;
  }
}
onMounted(() => void load());
onBeforeUnmount(() => { listRequest++; detailRequest++; });
</script>

<template>
  <div class="mx-auto w-full max-w-[1600px] space-y-6 px-6 py-6">
    <PageHeader
      title="消息中心"
      description="查看分析报告、市场提醒与系统消息。"
    />
    <form
      class="space-y-3 rounded-xl border bg-card p-4"
      @submit.prevent="search"
    >
      <div class="grid grid-cols-[minmax(200px,1fr)_140px_140px_minmax(210px,1fr)_minmax(210px,1fr)] items-end gap-3">
        <div class="space-y-2">
          <Label for="notification-keyword">关键词</Label>
          <Input
            id="notification-keyword"
            v-model="keyword"
            placeholder="搜索标题或内容"
          />
        </div>
        <div class="space-y-2">
          <Label for="notification-type">消息类型</Label>
          <Select v-model="routeType">
            <SelectTrigger id="notification-type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">
                全部类型
              </SelectItem>
              <SelectItem
                v-for="(label, value) in types"
                :key="value"
                :value="value"
              >
                {{ label }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div class="space-y-2">
          <Label for="notification-severity">严重级别</Label>
          <Select v-model="severity">
            <SelectTrigger id="notification-severity">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">
                全部级别
              </SelectItem>
              <SelectItem
                v-for="(label, value) in levels"
                :key="value"
                :value="value"
              >
                {{ label }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <AppDateTimePicker
          v-model="startTime"
          label="开始时间（本机时区）"
        />
        <AppDateTimePicker
          v-model="endTime"
          label="结束时间（本机时区）"
        />
      </div>
      <p
        v-if="invalidRange"
        class="text-sm text-destructive"
        role="alert"
      >
        开始时间不能晚于结束时间。
      </p>
      <div class="flex justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          @click="reset"
        >
          重置
        </Button>
        <Button
          type="submit"
          :disabled="invalidRange || loading"
        >
          查询
        </Button>
      </div>
    </form>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试"
      @action="load(page)"
    />
    <div
      class="overflow-hidden rounded-xl border bg-card"
      :aria-busy="loading"
    >
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead class="w-48">
              时间
            </TableHead><TableHead class="w-28">
              类型
            </TableHead>
            <TableHead class="w-24">
              级别
            </TableHead><TableHead>标题 / 摘要</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-if="loading">
            <TableCell
              :colspan="4"
              class="py-12 text-center text-muted-foreground"
            >
              加载消息中…
            </TableCell>
          </TableRow>
          <TableRow v-else-if="!items.length">
            <TableCell
              :colspan="4"
              class="py-12 text-center text-muted-foreground"
            >
              暂无符合条件的消息
            </TableCell>
          </TableRow>
          <template v-else>
            <TableRow
              v-for="item in items"
              :key="item.id"
              class="cursor-pointer"
              @click="showDetail(item.id)"
            >
              <TableCell class="text-xs text-muted-foreground">
                {{ formatDateTimeInDisplayTimezone(item.createdAt) }}
              </TableCell>
              <TableCell>{{ types[item.routeType] || item.routeType }}</TableCell>
              <TableCell>
                <Badge :variant="['error', 'critical'].includes(item.severity) ? 'destructive' : 'secondary'">
                  {{ levels[item.severity] || item.severity }}
                </Badge>
              </TableCell>
              <TableCell class="max-w-xl">
                <button
                  class="text-left font-medium hover:underline focus-visible:underline"
                  @click.stop="showDetail(item.id)"
                >
                  {{ item.title }}
                </button>
                <p class="mt-1 line-clamp-2 break-words text-sm text-muted-foreground">
                  {{ item.contentPreview }}
                </p>
              </TableCell>
            </TableRow>
          </template>
        </TableBody>
      </Table>
    </div>
    <div class="flex items-center justify-between">
      <p class="text-sm text-muted-foreground">
        共 {{ total }} 条消息
      </p>
      <AppPagination
        :current-page="page"
        :total-pages="totalPages"
        @page-change="load"
      />
    </div>
    <Dialog v-model:open="open">
      <DialogScrollContent class="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>{{ detail?.title || '消息详情' }}</DialogTitle>
          <DialogDescription>{{ detail ? `${formatDateTimeInDisplayTimezone(detail.createdAt)} · ${types[detail.routeType] || detail.routeType} · ${levels[detail.severity] || detail.severity}` : '查看完整消息内容' }}</DialogDescription>
        </DialogHeader>
        <p
          v-if="detailLoading"
          class="py-8 text-center text-muted-foreground"
        >
          加载消息中…
        </p>
        <AppApiErrorAlert
          v-else-if="detailError"
          :error="detailError"
        />
        <div
          v-else-if="detail"
          class="prose prose-sm min-w-0 max-w-none break-words dark:prose-invert"
          v-html="renderMarkdownToHtml(detail.content)"
        />
      </DialogScrollContent>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { getParsedApiError } from '@/api/error';
import { stocksApi, type ExtractItem } from '@/api/stocks';
import { systemConfigApi, SystemConfigConflictError } from '@/api/systemConfig';
import Badge from '@/components/common/Badge.vue';
import Button from '@/components/common/Button.vue';
import InlineAlert from '@/components/common/InlineAlert.vue';
import {
  getConfidenceMeta,
  mergeItems,
  normalizeConfidence,
  type ItemWithChecked,
} from '@/components/settings/intelligentImportMerge';
import { ref, computed } from 'vue';

const IMG_EXT = ['.jpg', '.jpeg', '.png', '.webp', '.gif'];
const IMG_MAX = 5 * 1024 * 1024;
const FILE_MAX = 2 * 1024 * 1024;
const TEXT_MAX = 100 * 1024;

const props = withDefaults(
  defineProps<{
    stockListValue: string;
    configVersion: string;
    maskToken: string;
    disabled?: boolean;
  }>(),
  { disabled: false },
);

const emit = defineEmits<{
  merged: [newValue: string];
}>();

const items = ref<ItemWithChecked[]>([]);
const isLoading = ref(false);
const isMerging = ref(false);
const error = ref<string | null>(null);
const isDragging = ref(false);
const pasteText = ref('');
const imageInputRef = ref<HTMLInputElement | null>(null);
const dataFileInputRef = ref<HTMLInputElement | null>(null);

function parseCurrentList() {
  return props.stockListValue
    .split(',')
    .map((c) => c.trim())
    .filter(Boolean);
}

function addItems(newItems: ExtractItem[]) {
  items.value = mergeItems(items.value, newItems);
}

async function handleImageFile(file: File) {
  const ext = `.${(file.name.split('.').pop() ?? '').toLowerCase()}`;
  if (!IMG_EXT.includes(ext)) {
    error.value = '图片仅支持 JPG、PNG、WebP、GIF';
    return;
  }
  if (file.size > IMG_MAX) {
    error.value = '图片不超过 5MB';
    return;
  }
  error.value = null;
  isLoading.value = true;
  try {
    const res = await stocksApi.extractFromImage(file);
    addItems(res.items ?? res.codes.map((c) => ({ code: c, name: null, confidence: 'medium' })));
  } catch (e) {
    const parsed = getParsedApiError(e);
    const err = e && typeof e === 'object' ? (e as { response?: { status?: number }; code?: string }) : null;
    let fallback = '识别失败，请重试';
    if (err?.response?.status === 429) fallback = '请求过于频繁，请稍后再试';
    else if (err?.code === 'ECONNABORTED') fallback = '请求超时，请检查网络后重试';
    error.value = parsed.message || fallback;
  } finally {
    isLoading.value = false;
  }
}

async function handleDataFile(file: File) {
  if (file.size > FILE_MAX) {
    error.value = '文件不超过 2MB';
    return;
  }
  error.value = null;
  isLoading.value = true;
  try {
    const res = await stocksApi.parseImport(file);
    addItems(res.items ?? res.codes.map((c) => ({ code: c, name: null, confidence: 'medium' })));
  } catch (e) {
    const parsed = getParsedApiError(e);
    error.value = parsed.message || '解析失败';
  } finally {
    isLoading.value = false;
  }
}

function handlePasteParse() {
  const t = pasteText.value.trim();
  if (!t) return;
  if (new Blob([t]).size > TEXT_MAX) {
    error.value = '粘贴文本不超过 100KB';
    return;
  }
  error.value = null;
  isLoading.value = true;
  stocksApi
    .parseImport(undefined, t)
    .then((res) => {
      addItems(res.items ?? res.codes.map((c) => ({ code: c, name: null, confidence: 'medium' })));
      pasteText.value = '';
    })
    .catch((e) => {
      const parsed = getParsedApiError(e);
      error.value = parsed.message || '解析失败';
    })
    .finally(() => {
      isLoading.value = false;
    });
}

function onDrop(e: DragEvent) {
  e.preventDefault();
  isDragging.value = false;
  if (props.disabled || isLoading.value) return;
  const f = e.dataTransfer?.files?.[0];
  if (!f) return;
  const ext = `.${(f.name.split('.').pop() ?? '').toLowerCase()}`;
  if (IMG_EXT.includes(ext)) void handleImageFile(f);
  else void handleDataFile(f);
}

function onImageInput(e: Event) {
  const t = e.target as HTMLInputElement;
  const f = t.files?.[0];
  if (f) void handleImageFile(f);
  t.value = '';
}

function onDataFileInput(e: Event) {
  const t = e.target as HTMLInputElement;
  const f = t.files?.[0];
  if (f) void handleDataFile(f);
  t.value = '';
}

function openFilePicker(inputRef: HTMLInputElement | null) {
  if (props.disabled || isLoading.value) {
    return;
  }
  inputRef?.click();
}

function toggleChecked(id: string) {
  items.value = items.value.map((p) => (p.id === id && p.code ? { ...p, checked: !p.checked } : p));
}

function toggleAll(checked: boolean) {
  items.value = items.value.map((p) => (p.code ? { ...p, checked } : p));
}

function removeItem(id: string) {
  items.value = items.value.filter((p) => p.id !== id);
}

function clearAll() {
  items.value = [];
  pasteText.value = '';
  error.value = null;
}

async function mergeToWatchlist() {
  const toMerge = items.value.filter((i) => i.checked && i.code).map((i) => i.code!);
  if (toMerge.length === 0) return;
  if (!props.configVersion) {
    error.value = '请先加载配置后再合并';
    return;
  }
  const current = parseCurrentList();
  const merged = [...new Set([...current, ...toMerge])];
  const value = merged.join(',');

  isMerging.value = true;
  error.value = null;
  try {
    await systemConfigApi.update({
      configVersion: props.configVersion,
      maskToken: props.maskToken,
      reloadNow: true,
      items: [{ key: 'STOCK_LIST', value }],
    });
    items.value = [];
    pasteText.value = '';
    emit('merged', value);
  } catch (e) {
    if (e instanceof SystemConfigConflictError) {
      emit('merged', value);
      error.value = '配置已更新，请再次点击「合并到自选股」';
    } else {
      error.value = e instanceof Error ? e.message : '合并保存失败';
    }
  } finally {
    isMerging.value = false;
  }
}

const validCount = computed(() => items.value.filter((i) => i.code).length);
const checkedCount = computed(() => items.value.filter((i) => i.checked && i.code).length);
</script>

<template>
  <div class="space-y-4">
    <div class="settings-surface-panel settings-border-strong rounded-xl border p-4 shadow-soft-card">
      <p class="text-sm font-medium text-foreground">支持图片、CSV/Excel 文件与剪贴板文本</p>
      <p class="mt-1 text-xs leading-5 text-secondary-text">
        图片识别需预先配置 Vision 模型。建议先人工核对解析结果，再合并到自选股。
      </p>
    </div>

    <div
      class="flex min-h-[96px] flex-col gap-4 rounded-xl border border-dashed p-4 transition-colors"
      :class="[
        isDragging ? 'settings-drag-active' : 'settings-border-strong settings-surface-overlay-soft',
        disabled || isLoading ? 'cursor-not-allowed opacity-60' : '',
      ]"
      @drop="onDrop"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
    >
      <div class="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="settings-secondary"
          :disabled="disabled || isLoading"
          @click="openFilePicker(imageInputRef)"
        >
          选择图片
        </Button>
        <input
          ref="imageInputRef"
          type="file"
          accept=".jpg,.jpeg,.png,.webp,.gif"
          class="hidden"
          :disabled="disabled || isLoading"
          @change="onImageInput"
        />
        <Button
          type="button"
          variant="settings-secondary"
          :disabled="disabled || isLoading"
          @click="openFilePicker(dataFileInputRef)"
        >
          选择文件
        </Button>
        <input
          ref="dataFileInputRef"
          type="file"
          accept=".csv,.xlsx,.txt"
          class="hidden"
          :disabled="disabled || isLoading"
          @change="onDataFileInput"
        />
      </div>
      <div class="flex flex-col gap-2 sm:flex-row">
        <textarea
          v-model="pasteText"
          placeholder="或粘贴 CSV/Excel 复制的文本..."
          class="input-surface settings-surface-strong settings-border-strong min-h-[72px] w-full rounded-xl border px-3 py-2 text-sm text-foreground shadow-none transition-colors placeholder:text-muted-text focus:outline-none"
          :disabled="disabled || isLoading"
        />
        <Button
          type="button"
          variant="settings-secondary"
          class="shrink-0 sm:self-start"
          :disabled="disabled || isLoading || !pasteText.trim()"
          @click="handlePasteParse"
        >
          解析
        </Button>
      </div>
    </div>

    <p v-if="isLoading" class="text-sm text-secondary-text">处理中...</p>
    <InlineAlert v-if="error" variant="danger" class="rounded-xl px-3 py-2 text-sm shadow-none">
      {{ error }}
    </InlineAlert>

    <div v-if="items.length > 0" class="space-y-2">
      <InlineAlert variant="warning" class="rounded-xl px-3 py-2 text-xs shadow-none">
        建议人工逐条核对后再合并。高置信度默认勾选，中/低置信度需手动确认。
      </InlineAlert>
      <div class="flex items-center justify-between">
        <span class="text-xs text-secondary-text">
          共 {{ validCount }} 条可合并，已勾选 {{ checkedCount }} 条
        </span>
        <div class="flex gap-2">
          <button
            type="button"
            class="text-xs text-secondary-text transition-colors hover:text-foreground"
            @click="toggleAll(true)"
          >
            全选
          </button>
          <button
            type="button"
            class="text-xs text-secondary-text transition-colors hover:text-foreground"
            @click="toggleAll(false)"
          >
            取消
          </button>
          <button
            type="button"
            class="text-xs text-secondary-text transition-colors hover:text-foreground"
            @click="clearAll"
          >
            清空
          </button>
        </div>
      </div>
      <div class="max-h-[220px] space-y-1 overflow-y-auto rounded-xl border settings-border-strong settings-surface-overlay-soft p-2">
        <div
          v-for="it in items"
          :key="it.id"
          class="flex items-center gap-2 rounded-xl border px-3 py-2 text-sm"
          :class="
            it.code
              ? 'settings-border bg-[var(--settings-surface-strong)]'
              : 'border-danger/25 bg-danger/10'
          "
        >
          <input
            type="checkbox"
            :checked="it.checked"
            :disabled="!it.code || disabled"
            class="settings-input-checkbox h-4 w-4 rounded border-border/70 bg-base"
            @change="toggleChecked(it.id)"
          />
          <span :class="it.code ? 'font-medium text-foreground' : 'font-medium text-danger'">
            {{ it.code || '解析失败' }}
          </span>
          <span v-if="it.name" class="text-secondary-text">({{ it.name }})</span>
          <div class="ml-auto flex items-center gap-2">
            <Badge :variant="getConfidenceMeta(normalizeConfidence(it.confidence)).badge" size="sm">
              {{ getConfidenceMeta(normalizeConfidence(it.confidence)).label }}
            </Badge>
            <button
              type="button"
              class="text-secondary-text transition-colors hover:text-foreground"
              :disabled="disabled"
              @click="removeItem(it.id)"
            >
              ×
            </button>
          </div>
        </div>
      </div>
      <Button
        type="button"
        variant="primary"
        class="mt-2"
        :disabled="disabled || isMerging || checkedCount === 0"
        @click="mergeToWatchlist()"
      >
        {{ isMerging ? '保存中...' : '合并到自选股' }}
      </Button>
    </div>
  </div>
</template>

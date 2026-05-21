<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { watchListApi, type WatchListItem, type WatchListItemCreate } from '@/api/watchList';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import Input from '@/components/common/Input.vue';
import StockAutocomplete from '@/components/StockAutocomplete/StockAutocomplete.vue';
import { looksLikeStockCode } from '@/utils/validation';
import { Eye, Pencil, Plus, Star, Trash2, X } from 'lucide-vue-next';
import { onMounted, ref, watch } from 'vue';

// ── State ─────────────────────────────────────────────────────────────────────
const items = ref<WatchListItem[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);

// Dialog state
const showDialog = ref(false);
const editingId = ref<number | null>(null);
const formStockQuery = ref('');
const formCode = ref('');
const formName = ref('');
const formNotes = ref('');
const formError = ref<string | null>(null);
const saving = ref(false);

const showDeleteConfirm = ref(false);
const deletingId = ref<number | null>(null);
const deletingCode = ref('');

function formatStockQuery(code: string, name?: string | null): string {
  return name ? `${name}（${code}）` : code;
}

watch(formStockQuery, (value) => {
  if (!formCode.value) return;
  const selectedQuery = formatStockQuery(formCode.value, formName.value);
  if (value !== selectedQuery && value !== formCode.value) {
    formCode.value = '';
    formName.value = '';
  }
});

// ── API Calls ─────────────────────────────────────────────────────────────────
async function loadList() {
  loading.value = true;
  error.value = null;
  try {
    const res = await watchListApi.list();
    items.value = res.items;
    total.value = res.total;
  } catch (e) {
    error.value = getParsedApiError(e);
  } finally {
    loading.value = false;
  }
}

async function save() {
  formError.value = null;
  const query = formStockQuery.value.trim();
  const code = (formCode.value.trim() || (looksLikeStockCode(query) ? query : '')).toUpperCase();
  if (!code) {
    formError.value = '请先搜索并选择股票';
    return;
  }
  saving.value = true;
  try {
    if (editingId.value !== null) {
      const updated = await watchListApi.update(editingId.value, {
        name: formName.value.trim() || undefined,
        notes: formNotes.value.trim() || undefined,
      });
      const idx = items.value.findIndex((i) => i.id === editingId.value);
      if (idx !== -1) items.value[idx] = updated;
    } else {
      const body: WatchListItemCreate = {
        code,
        name: formName.value.trim() || undefined,
        notes: formNotes.value.trim() || undefined,
      };
      const created = await watchListApi.create(body);
      items.value.push(created);
      total.value++;
    }
    closeDialog();
  } catch (e) {
    const parsed = getParsedApiError(e);
    formError.value = parsed.message || '操作失败，请重试';
  } finally {
    saving.value = false;
  }
}

async function confirmDelete() {
  if (deletingId.value === null) return;
  try {
    await watchListApi.remove(deletingId.value);
    items.value = items.value.filter((i) => i.id !== deletingId.value);
    total.value--;
  } catch (e) {
    error.value = getParsedApiError(e);
  } finally {
    showDeleteConfirm.value = false;
    deletingId.value = null;
    deletingCode.value = '';
  }
}

// ── Dialog helpers ────────────────────────────────────────────────────────────
function openCreate() {
  editingId.value = null;
  formStockQuery.value = '';
  formCode.value = '';
  formName.value = '';
  formNotes.value = '';
  formError.value = null;
  showDialog.value = true;
}

function openEdit(item: WatchListItem) {
  editingId.value = item.id;
  formCode.value = item.code;
  formName.value = item.name ?? '';
  formStockQuery.value = formatStockQuery(item.code, item.name);
  formNotes.value = item.notes ?? '';
  formError.value = null;
  showDialog.value = true;
}

function closeDialog() {
  showDialog.value = false;
  editingId.value = null;
}

function handleStockAutocompleteSubmit(code: string, name?: string) {
  formCode.value = code;
  formName.value = name ?? '';
  formStockQuery.value = formatStockQuery(code, name);
}

function openDelete(item: WatchListItem) {
  deletingId.value = item.id;
  deletingCode.value = item.code;
  showDeleteConfirm.value = true;
}

onMounted(loadList);
</script>

<template>
  <div class="mx-auto w-full px-4 py-6 sm:px-6">
    <!-- Header -->
    <div class="mb-6 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary-gradient text-[hsl(var(--primary-foreground))] shadow-soft-card">
          <Star class="h-5 w-5" />
        </div>
        <div>
          <h1 class="text-lg font-semibold text-foreground">自选股</h1>
          <p class="text-xs text-secondary-text">共 {{ total }} 只</p>
        </div>
      </div>
      <Button variant="primary" size="sm" @click="openCreate">
        <Plus class="mr-1.5 h-4 w-4" />
        添加
      </Button>
    </div>

    <!-- Error -->
    <ApiErrorAlert v-if="error" :error="error" class="mb-4" />

    <!-- Loading skeleton -->
    <div v-if="loading" class="space-y-2">
      <div v-for="n in 4" :key="n" class="h-14 animate-pulse rounded-xl bg-card" />
    </div>

    <!-- Empty state -->
    <div
      v-else-if="!items.length"
      class="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-border/60 py-16 text-center"
    >
      <Eye class="h-10 w-10 text-secondary-text/40" />
      <p class="text-sm text-secondary-text">暂无自选股，点击「添加」开始关注</p>
    </div>

    <!-- List -->
    <div v-else class="space-y-2">
      <div
        v-for="item in items"
        :key="item.id"
        class="flex items-center gap-3 rounded-xl border border-border/60 bg-card px-4 py-3 transition-colors hover:bg-hover"
      >
        <!-- Code badge -->
        <span class="min-w-[72px] rounded-lg bg-primary/10 px-2 py-0.5 text-center text-sm font-mono font-semibold text-primary">
          {{ item.code }}
        </span>
        <!-- Name & notes -->
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium text-foreground">
            {{ item.name || '—' }}
          </p>
          <p v-if="item.notes" class="truncate text-xs text-secondary-text">{{ item.notes }}</p>
        </div>
        <!-- Actions -->
        <div class="flex shrink-0 items-center gap-1">
          <button
            class="rounded-lg p-1.5 text-secondary-text hover:bg-hover hover:text-foreground"
            aria-label="编辑"
            @click="openEdit(item)"
          >
            <Pencil class="h-4 w-4" />
          </button>
          <button
            class="rounded-lg p-1.5 text-secondary-text hover:bg-destructive/10 hover:text-destructive"
            aria-label="删除"
            @click="openDelete(item)"
          >
            <Trash2 class="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>

    <!-- Add / Edit Dialog -->
    <Teleport to="body">
      <div
        v-if="showDialog"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="closeDialog"
      >
        <div class="w-full max-w-md rounded-2xl border border-border bg-card p-6 shadow-2xl">
          <div class="mb-5 flex items-center justify-between">
            <h2 class="text-base font-semibold text-foreground">
              {{ editingId !== null ? '编辑自选股' : '添加自选股' }}
            </h2>
            <button class="rounded-lg p-1 text-secondary-text hover:text-foreground" @click="closeDialog">
              <X class="h-5 w-5" />
            </button>
          </div>

          <div class="space-y-4">
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">股票 *</label>
              <StockAutocomplete
                v-model="formStockQuery"
                placeholder="搜索股票代码、名称或拼音"
                :disabled="editingId !== null"
                @submit="handleStockAutocompleteSubmit"
              />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">备注（可选）</label>
              <Input v-model="formNotes" placeholder="备注信息" />
            </div>
            <p v-if="formError" class="text-sm text-destructive">{{ formError }}</p>
          </div>

          <div class="mt-6 flex justify-end gap-3">
            <Button variant="ghost" @click="closeDialog">取消</Button>
            <Button variant="primary" :disabled="saving" @click="save">
              {{ saving ? '保存中…' : '保存' }}
            </Button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Delete Confirm Dialog -->
    <Teleport to="body">
      <div
        v-if="showDeleteConfirm"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
        @click.self="showDeleteConfirm = false"
      >
        <div class="w-full max-w-sm rounded-2xl border border-border bg-card p-6 shadow-2xl">
          <h2 class="mb-2 text-base font-semibold text-foreground">删除自选股</h2>
          <p class="mb-5 text-sm text-secondary-text">
            确认从自选股中移除 <span class="font-mono font-semibold text-foreground">{{ deletingCode }}</span>？
          </p>
          <div class="flex justify-end gap-3">
            <Button variant="ghost" @click="showDeleteConfirm = false">取消</Button>
            <Button variant="danger" @click="confirmDelete">确认删除</Button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { stockListApi, type StockHolding, type StockHoldingCreate } from '@/api/stockList';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import Button from '@/components/common/Button.vue';
import Input from '@/components/common/Input.vue';
import { Briefcase, Pencil, Plus, Trash2, X } from 'lucide-vue-next';
import { computed, onMounted, ref } from 'vue';

// ── State ─────────────────────────────────────────────────────────────────────
const items = ref<StockHolding[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);

const totalQuantity = computed(() => items.value.reduce((s, i) => s + i.quantity, 0));

// Dialog state
const showDialog = ref(false);
const editingId = ref<number | null>(null);
const formCode = ref('');
const formName = ref('');
const formQuantity = ref('0');
const formNotes = ref('');
const formError = ref<string | null>(null);
const saving = ref(false);

const showDeleteConfirm = ref(false);
const deletingId = ref<number | null>(null);
const deletingCode = ref('');

// ── API Calls ─────────────────────────────────────────────────────────────────
async function loadList() {
  loading.value = true;
  error.value = null;
  try {
    const res = await stockListApi.list();
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
  const code = formCode.value.trim().toUpperCase();
  if (!code) {
    formError.value = '股票代码不能为空';
    return;
  }
  const qty = parseInt(formQuantity.value, 10);
  if (isNaN(qty) || qty < 0) {
    formError.value = '持仓数量必须为非负整数';
    return;
  }
  saving.value = true;
  try {
    if (editingId.value !== null) {
      const updated = await stockListApi.update(editingId.value, {
        name: formName.value.trim() || undefined,
        quantity: qty,
        notes: formNotes.value.trim() || undefined,
      });
      const idx = items.value.findIndex((i) => i.id === editingId.value);
      if (idx !== -1) items.value[idx] = updated;
    } else {
      const body: StockHoldingCreate = {
        code,
        name: formName.value.trim() || undefined,
        quantity: qty,
        notes: formNotes.value.trim() || undefined,
      };
      const created = await stockListApi.create(body);
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
    await stockListApi.remove(deletingId.value);
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
  formCode.value = '';
  formName.value = '';
  formQuantity.value = '0';
  formNotes.value = '';
  formError.value = null;
  showDialog.value = true;
}

function openEdit(item: StockHolding) {
  editingId.value = item.id;
  formCode.value = item.code;
  formName.value = item.name ?? '';
  formQuantity.value = String(item.quantity);
  formNotes.value = item.notes ?? '';
  formError.value = null;
  showDialog.value = true;
}

function closeDialog() {
  showDialog.value = false;
  editingId.value = null;
}

function openDelete(item: StockHolding) {
  deletingId.value = item.id;
  deletingCode.value = item.code;
  showDeleteConfirm.value = true;
}

onMounted(loadList);
</script>

<template>
  <div class="mx-auto max-w-3xl px-4 py-6 sm:px-6">
    <!-- Header -->
    <div class="mb-6 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary-gradient text-[hsl(var(--primary-foreground))] shadow-soft-card">
          <Briefcase class="h-5 w-5" />
        </div>
        <div>
          <h1 class="text-lg font-semibold text-foreground">持仓股</h1>
          <p class="text-xs text-secondary-text">{{ total }} 只 · 总持仓 {{ totalQuantity.toLocaleString() }} 股</p>
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
      <Briefcase class="h-10 w-10 text-secondary-text/40" />
      <p class="text-sm text-secondary-text">暂无持仓股，点击「添加」开始记录</p>
      <p class="text-xs text-secondary-text/60">持仓股列表同时作为每日分析的目标股票</p>
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
        <!-- Quantity badge -->
        <span class="shrink-0 rounded-lg border border-border/60 bg-background px-2.5 py-0.5 text-sm font-semibold tabular-nums text-foreground">
          {{ item.quantity.toLocaleString() }} 股
        </span>
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
              {{ editingId !== null ? '编辑持仓股' : '添加持仓股' }}
            </h2>
            <button class="rounded-lg p-1 text-secondary-text hover:text-foreground" @click="closeDialog">
              <X class="h-5 w-5" />
            </button>
          </div>

          <div class="space-y-4">
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">股票代码 *</label>
              <Input
                v-model="formCode"
                placeholder="如 600519"
                :disabled="editingId !== null"
                class="uppercase"
              />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">名称（可选）</label>
              <Input v-model="formName" placeholder="如 贵州茅台" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-foreground">持仓数量（股）</label>
              <Input v-model="formQuantity" type="number" min="0" placeholder="0" />
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
          <h2 class="mb-2 text-base font-semibold text-foreground">删除持仓股</h2>
          <p class="mb-5 text-sm text-secondary-text">
            确认从持仓股中移除
            <span class="font-mono font-semibold text-foreground">{{ deletingCode }}</span>？
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

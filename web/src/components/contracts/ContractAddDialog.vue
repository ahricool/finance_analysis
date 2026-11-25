<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { Plus, Search, Check } from 'lucide-vue-next';
import { contractsApi, type Contract } from '@/api/contracts';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';

const props = defineProps<{ open: boolean; existing: string[]; busy: boolean; addError: ParsedApiError | null }>();
const emit = defineEmits<{ 'update:open': [value: boolean]; add: [item: Contract] }>();
const query = ref('');
const results = ref<Contract[]>([]);
const searching = ref(false);
const searched = ref(false);
const error = ref<ParsedApiError | null>(null);
let generation = 0;
let request: AbortController | undefined;
let timer: ReturnType<typeof setTimeout> | undefined;
function reset() {
  ++generation;
  request?.abort(); request = undefined;
  clearTimeout(timer);
  results.value = [];
  searching.value = false;
  searched.value = false;
  error.value = null;
}
async function search() {
  clearTimeout(timer);
  const q = query.value.trim();
  if (!props.open || !q) return;
  const version = ++generation;
  request?.abort();
  const controller = new AbortController();
  request = controller;
  searching.value = true;
  searched.value = false;
  error.value = null;
  try {
    const found = await contractsApi.search(q, controller.signal);
    if (version === generation) { results.value = found; searched.value = true; }
  } catch (reason) {
    if (version === generation) error.value = getParsedApiError(reason);
  } finally {
    if (version === generation) { request = undefined; searching.value = false; }
  }
}
watch(query, () => {
  reset();
  if (props.open && query.value.trim()) timer = setTimeout(() => { void search(); }, 300);
});
watch(() => props.open, open => { if (!open) { reset(); query.value = ''; } });
onBeforeUnmount(reset);
</script>

<template>
  <Dialog
    :open="open"
    @update:open="emit('update:open', $event)"
  >
    <DialogContent class="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>添加合约</DialogTitle>
        <DialogDescription>搜索交易中的 USDT 本位永续合约，点击添加即可加入共享行情列表。</DialogDescription>
      </DialogHeader>
      <form
        class="flex items-center gap-2"
        @submit.prevent="search"
      >
        <Input
          v-model="query"
          class="min-w-0 flex-1"
          placeholder="例如 BTC、NVDA、ETH"
          aria-label="搜索合约"
          maxlength="32"
        />
        <Button
          type="submit"
          variant="outline"
          :disabled="searching || !query.trim()"
        >
          <Search class="size-4" /> 搜索
        </Button>
      </form>
      <AppApiErrorAlert
        v-if="error || addError"
        :error="(error || addError)!"
      />
      <p
        v-if="busy"
        class="text-xs text-muted-foreground"
        role="status"
      >
        正在更新共享列表…
      </p>
      <p
        v-if="searching"
        class="py-6 text-center text-sm text-muted-foreground"
        role="status"
      >
        正在搜索…
      </p>
      <div
        v-else-if="results.length"
        class="max-h-[min(45dvh,22rem)] divide-y overflow-y-auto rounded-lg border"
      >
        <div
          v-for="item in results"
          :key="item.symbol"
          class="flex items-center justify-between gap-3 p-3"
        >
          <div class="min-w-0">
            <p class="font-semibold break-words">
              {{ item.symbol }}
            </p>
            <p class="text-xs text-muted-foreground">
              {{ item.underlying_symbol?.replace(/\.(CRYPTO|OTHER)$/, '') ?? item.category }}
            </p>
          </div>
          <Button
            size="sm"
            :variant="existing.includes(item.symbol) ? 'outline' : 'default'"
            :disabled="busy || existing.includes(item.symbol)"
            :aria-label="item.symbol + (existing.includes(item.symbol) ? ' 已添加' : ' · 添加')"
            @click="emit('add', item)"
          >
            <Check
              v-if="existing.includes(item.symbol)"
              class="size-4"
            />
            <Plus
              v-else
              class="size-4"
            />
            {{ existing.includes(item.symbol) ? '已添加' : '添加' }}
          </Button>
        </div>
      </div>
      <p
        v-else
        class="py-6 text-center text-sm text-muted-foreground"
      >
        {{ searched ? '未找到交易中的 USDT 永续合约。' : '输入合约代码搜索。' }}
      </p>
    </DialogContent>
  </Dialog>
</template>

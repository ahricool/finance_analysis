<script setup lang="ts">
import { onMounted, ref } from 'vue';
import FieldSelect from '@/components/forms/FieldSelect.vue';
import { loadCatalog, selectStrategy, type Catalog, type Environment } from '@/api/cryptoStrategy';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';

const props = defineProps<{ environment: Environment }>();
const catalog = ref<Catalog>();
const busy = ref(false);
const error = ref<ParsedApiError | null>(null);
async function load() {
  try { catalog.value = await loadCatalog(); error.value = null; }
  catch (e) { error.value = getParsedApiError(e); }
}
async function change(value: string) {
  if (busy.value) return;
  busy.value = true;
  try { await selectStrategy(props.environment, value); await load(); }
  catch (e) { error.value = getParsedApiError(e); }
  finally { busy.value = false; }
}
onMounted(load);
</script>

<template>
  <div class="space-y-2 border-t pt-4">
    <FieldSelect
      label="交易策略"
      :model-value="catalog?.selected[environment] ?? ''"
      :disabled="busy || !catalog"
      :options="(catalog?.items ?? []).map(i => ({ value: i.key, label: i.name }))"
      @change="change"
    />
    <p class="text-xs text-muted-foreground">
      切换时按账户权益结算上一策略区间。
    </p>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="刷新"
      @action="load"
    />
  </div>
</template>

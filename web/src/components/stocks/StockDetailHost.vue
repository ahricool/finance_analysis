<script setup lang="ts">
import { defineAsyncComponent, onBeforeUnmount, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useStockDetail } from '@/composables/useStockDetail';
const StockDetailDialog = defineAsyncComponent(() => import('./StockDetailDialog.vue'));
const { selection, close } = useStockDetail();
const route = useRoute();
watch(() => route.fullPath, close);
onBeforeUnmount(close);
</script>
<template>
  <StockDetailDialog
    v-if="selection"
    :stock="selection.stock"
    :context="selection.context"
    kind="research"
    @update:open="value => { if (!value) close(); }"
  />
</template>

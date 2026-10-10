<script setup lang="ts">
import { RouterView } from 'vue-router';
import ModuleLayout from '@/components/layout/ModuleLayout.vue';
import { cryptoNavItems } from '@/config/mainNav';
</script>

<template>
  <div class="page-shell">
    <ModuleLayout
      :items="cryptoNavItems"
      active-key="crypto-btc"
      label="加密货币页面导航"
    >
      <RouterView />
    </ModuleLayout>
  </div>
</template>

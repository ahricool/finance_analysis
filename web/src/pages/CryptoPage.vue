<script setup lang="ts">
import { RouterView, useRoute } from 'vue-router';
import { computed } from 'vue';
import { useAuthStore } from '@/stores/authStore';
import ModuleLayout from '@/components/layout/ModuleLayout.vue';
import { cryptoNavItems } from '@/config/mainNav';
const route = useRoute();
const auth = useAuthStore();
const items = computed(() => cryptoNavItems.filter(item => !item.adminOnly || auth.currentUser?.role === 'admin'));
</script>

<template>
  <div class="page-shell">
    <ModuleLayout
      :items="items"
      :active-key="String(route.name)"
      label="加密货币页面导航"
    >
      <RouterView />
    </ModuleLayout>
  </div>
</template>

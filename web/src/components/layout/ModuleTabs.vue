<script setup lang="ts">
import type { Component } from 'vue';
import type { RouteLocationRaw } from 'vue-router';
import { ScrollArea, ScrollBar } from '@/components/ui/scroll-area';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';

export type ModuleTab = { key: string; label: string; icon?: Component; to: RouteLocationRaw };
defineProps<{ items: ModuleTab[]; activeKey: string; label: string }>();
</script>

<template>
  <nav
    :aria-label="label"
    data-testid="module-tabs"
  >
    <ScrollArea class="w-full whitespace-nowrap">
      <Tabs :model-value="activeKey">
        <TabsList>
          <TabsTrigger
            v-for="item in items"
            :key="item.key"
            :value="item.key"
            as-child
          >
            <RouterLink :to="item.to">
              <component
                :is="item.icon"
                v-if="item.icon"
              />
              {{ item.label }}
            </RouterLink>
          </TabsTrigger>
        </TabsList>
      </Tabs>
      <template #horizontal-scrollbar>
        <ScrollBar orientation="horizontal" />
      </template>
    </ScrollArea>
  </nav>
</template>

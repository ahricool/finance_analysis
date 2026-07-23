<script setup lang="ts">
import SectionNavItems, { type SectionNavItem } from '@/components/common/SectionNavItems.vue';

withDefaults(defineProps<{
  items: SectionNavItem[];
  activeKey: string;
  responsive?: boolean;
}>(), {
  responsive: false,
});

const emit = defineEmits<{
  select: [key: string];
}>();
</script>

<template>
  <aside
    class="h-fit space-y-1 rounded-2xl border border-border/70 bg-card/94 p-2 font-sans shadow-soft-card backdrop-blur-sm"
  >
    <SectionNavItems
      :items="items"
      :active-key="activeKey"
      :responsive="responsive"
      @select="emit('select', $event)"
    />
  </aside>
</template>

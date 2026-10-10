<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useMediaQuery } from '@vueuse/core';
import { PanelLeft } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import ModuleTabs, { type ModuleTab } from './ModuleTabs.vue';

const props = defineProps<{ items: ModuleTab[]; activeKey: string; label: string }>();
const open = ref(false);
const route = useRoute();
const desktop = useMediaQuery('(min-width: 1024px)');
const activeLabel = computed(() => props.items.find((item) => item.key === props.activeKey)?.label);
watch([() => route.fullPath, desktop], () => { open.value = false; });
</script>

<template>
  <div
    class="grid min-w-0 items-start gap-4 lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-6"
    data-testid="module-layout"
  >
    <aside class="hidden min-w-0 lg:sticky lg:top-20 lg:block lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto">
      <ModuleTabs
        :items="items"
        :active-key="activeKey"
        :label="label"
      />
    </aside>
    <div class="min-w-0 lg:hidden">
      <Sheet v-model:open="open">
        <SheetTrigger as-child>
          <Button
            variant="outline"
            :aria-label="`打开${label}`"
            data-testid="module-nav-trigger"
          >
            <PanelLeft class="size-4" />
            {{ activeLabel || label }}
          </Button>
        </SheetTrigger>
        <SheetContent
          side="left"
          class="w-[min(20rem,85vw)]"
          :aria-describedby="undefined"
          data-testid="module-nav-sheet"
        >
          <SheetHeader>
            <SheetTitle>{{ label }}</SheetTitle>
          </SheetHeader>
          <div class="min-h-0 overflow-y-auto p-4 pt-0">
            <ModuleTabs
              :items="items"
              :active-key="activeKey"
              :label="label"
              @navigate="open = false"
            />
          </div>
        </SheetContent>
      </Sheet>
    </div>
    <div
      class="min-w-0 space-y-4"
      data-testid="module-content"
    >
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import type { TabsTriggerProps } from 'reka-ui';
import type { HTMLAttributes } from 'vue';
import { reactiveOmit } from '@vueuse/core';
import { TabsTrigger, useForwardProps } from 'reka-ui';
import { cn } from '@/utils/cn';

const props = defineProps<TabsTriggerProps & { class?: HTMLAttributes['class'] }>();
const delegatedProps = reactiveOmit(props, 'class');
const forwardedProps = useForwardProps(delegatedProps);
</script>

<template>
  <TabsTrigger
    data-slot="tabs-trigger"
    v-bind="forwardedProps"
    :class="cn(
      'inline-flex h-7 items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-transparent px-3 text-sm font-medium text-foreground/60 transition-all hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
      props.class,
    )"
  >
    <slot />
  </TabsTrigger>
</template>

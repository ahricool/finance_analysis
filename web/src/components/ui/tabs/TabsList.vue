<script setup lang="ts">
import type { TabsListProps } from 'reka-ui';
import type { HTMLAttributes } from 'vue';
import { reactiveOmit } from '@vueuse/core';
import { TabsList } from 'reka-ui';
import { cn } from '@/utils/cn';

const props = defineProps<TabsListProps & { class?: HTMLAttributes['class'] }>();
const delegatedProps = reactiveOmit(props, 'class');
</script>

<template>
  <TabsList
    data-slot="tabs-list"
    v-bind="delegatedProps"
    :class="cn('inline-flex h-10 w-max items-center justify-center rounded-lg bg-muted/80 p-1 text-muted-foreground ring-1 ring-border/50', props.class)"
  >
    <slot />
  </TabsList>
</template>

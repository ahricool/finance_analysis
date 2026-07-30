<script setup lang="ts">
import { cn } from '@/utils/cn';
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

const props = withDefaults(
  defineProps<{
    title: string;
    description?: string;
    class?: string;
  }>(),
  { description: '', class: '' },
);
</script>

<template>
  <Card :class="cn(props.class)">
    <CardHeader>
      <CardTitle>{{ title }}</CardTitle>
      <CardDescription v-if="description">
        {{ description }}
      </CardDescription>
      <CardAction v-if="$slots.actions">
        <slot name="actions" />
      </CardAction>
    </CardHeader>
    <CardContent class="space-y-5">
      <slot />
    </CardContent>
  </Card>
</template>

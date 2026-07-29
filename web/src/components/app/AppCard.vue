<script setup lang="ts">
import type { HTMLAttributes } from 'vue';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
const props = withDefaults(defineProps<{
  title?: string;
  subtitle?: string;
  padding?: 'none' | 'sm' | 'md' | 'lg';
  interactive?: boolean;
  class?: HTMLAttributes['class'];
}>(), { padding: 'md', interactive: false });
const paddings = { none: 'p-0', sm: 'p-4', md: 'p-5', lg: 'p-6' };
</script>

<template>
  <Card :class="cn(interactive && 'transition-colors hover:border-primary/30', props.class)">
    <CardHeader v-if="title || subtitle" class="pb-3">
      <CardTitle v-if="title">{{ title }}</CardTitle>
      <CardDescription v-if="subtitle">{{ subtitle }}</CardDescription>
    </CardHeader>
    <CardContent :class="cn((title || subtitle) ? 'pt-0' : '', paddings[padding])"><slot /></CardContent>
  </Card>
</template>

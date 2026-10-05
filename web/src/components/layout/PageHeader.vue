<script setup lang="ts">
import { Breadcrumb, BreadcrumbItem, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from '@/components/ui/breadcrumb';

withDefaults(defineProps<{
  /** Chinese primary title */
  title: string;
  /** Optional muted English subtitle under the Chinese title (never above). */
  en?: string;
  description?: string;
  section?: string;
  variant?: 'page' | 'section';
}>(), { description: '', section: '', en: '', variant: 'page' });
</script>

<template>
  <header
    :class="variant === 'page' ? 'md:flex-row md:items-end md:justify-between' : ''"
    class="flex flex-col gap-4 border-b border-border/60 pb-5"
  >
    <div class="min-w-0 space-y-2.5">
      <Breadcrumb v-if="section || $slots.breadcrumb">
        <BreadcrumbList>
          <slot name="breadcrumb">
            <BreadcrumbItem>{{ section }}</BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem><BreadcrumbPage>{{ title }}</BreadcrumbPage></BreadcrumbItem>
          </slot>
        </BreadcrumbList>
      </Breadcrumb>
      <div>
        <component
          :is="variant === 'section' ? 'h2' : 'h1'"
          class="font-semibold tracking-tight text-foreground"
          :class="variant === 'section' ? 'text-lg' : 'text-2xl sm:text-3xl'"
        >
          {{ title }}
        </component>
        <p
          v-if="en"
          class="mt-1 text-xs font-normal tracking-wide text-muted-foreground sm:text-sm"
        >
          {{ en }}
        </p>
        <p
          v-if="description"
          class="mt-1.5 max-w-3xl text-sm leading-relaxed text-muted-foreground"
          :class="variant === 'page' && 'sm:text-base'"
        >
          {{ description }}
        </p>
      </div>
    </div>
    <div
      v-if="$slots.actions"
      class="flex min-w-0 flex-wrap items-end gap-2"
      :class="variant === 'section' && 'research-toolbar'"
    >
      <slot name="actions" />
    </div>
  </header>
</template>

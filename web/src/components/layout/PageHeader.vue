<script setup lang="ts">
import { Breadcrumb, BreadcrumbItem, BreadcrumbList, BreadcrumbPage, BreadcrumbSeparator } from '@/components/ui/breadcrumb';

withDefaults(defineProps<{
  title: string;
  description?: string;
  section?: string;
}>(), { description: '', section: '' });
</script>

<template>
  <header class="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
    <div class="min-w-0 space-y-2">
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
        <h1 class="text-2xl font-semibold tracking-tight sm:text-3xl">
          {{ title }}
        </h1>
        <p
          v-if="description"
          class="mt-1 max-w-3xl text-sm text-muted-foreground sm:text-base"
        >
          {{ description }}
        </p>
      </div>
    </div>
    <div
      v-if="$slots.actions"
      class="flex shrink-0 flex-wrap items-center gap-2"
    >
      <slot name="actions" />
    </div>
  </header>
</template>

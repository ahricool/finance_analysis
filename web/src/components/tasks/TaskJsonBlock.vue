<script setup lang="ts">
import { ScrollArea } from '@/components/ui/scroll-area';

defineProps<{
  title: string;
  content: string;
}>();
</script>

<template>
  <section class="space-y-2">
    <h3 class="text-sm font-semibold">
      {{ title }}
    </h3>
    <ScrollArea class="max-h-64 rounded-md border bg-muted/40">
      <pre class="whitespace-pre-wrap break-words p-3 font-mono text-xs leading-relaxed text-muted-foreground">{{ content }}</pre>
    </ScrollArea>
  </section>
</template>

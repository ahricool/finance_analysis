<script setup lang="ts">
import { SlidersHorizontal } from 'lucide-vue-next';
import { Switch } from '@/components/ui/switch';
import type { Environment } from '@/api/cryptoStrategy';
import StrategySelect from './StrategySelect.vue';

defineProps<{ environment: Environment; heading: string; enabled: boolean; disabled: boolean; status: string }>();
defineEmits<{ change: [enabled: boolean] }>();
</script>

<template>
  <section class="flex min-w-0 flex-col gap-4 rounded-xl border bg-card p-5">
    <div class="flex items-center justify-between gap-4">
      <h2 class="flex items-center gap-2 text-base font-semibold">
        <SlidersHorizontal
          class="size-4 text-muted-foreground"
          aria-hidden="true"
        />
        {{ heading }}
      </h2>
      <Switch
        :aria-label="heading"
        :data-testid="environment + '-trading-switch'"
        :model-value="enabled"
        :disabled="disabled"
        @update:model-value="$emit('change', $event)"
      />
    </div>
    <p
      class="flex items-center gap-2 text-xs text-muted-foreground"
      :data-testid="environment + '-switch-status'"
      role="status"
    >
      <span :class="['size-2 shrink-0 rounded-full', enabled ? 'bg-brand' : 'bg-muted-foreground/50']" />
      {{ status }}
    </p>
    <StrategySelect :environment="environment" />
    <details class="mt-auto border-t pt-3 text-xs text-muted-foreground">
      <summary class="cursor-pointer font-medium">
        控制说明
      </summary>
      <div class="mt-2 space-y-1 leading-relaxed">
        <slot />
      </div>
    </details>
  </section>
</template>

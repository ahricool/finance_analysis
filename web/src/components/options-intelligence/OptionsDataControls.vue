<script setup lang="ts">
import ResearchDataModeToggle from '@/components/research/ResearchDataModeToggle.vue';
import AppDatePicker from '@/components/app/AppDatePicker.vue';
import type { OptionsView } from '@/api/optionsIntelligence';
defineProps<{ mode: OptionsView; date?: string; dates: string[] }>();
defineEmits<{ 'update:mode': [value: OptionsView]; 'update:date': [value: string] }>();
</script>
<template>
  <div
    class="flex flex-wrap items-end gap-3"
    data-testid="options-data-controls"
  >
    <ResearchDataModeToggle
      :mode="mode"
      :preview-available="true"
      @update:mode="$emit('update:mode', $event)"
    />
    <AppDatePicker
      v-if="mode === 'official'"
      :model-value="date"
      :available-dates="dates"
      :clearable="false"
      label="正式交易日"
      class="w-48"
      data-testid="options-date"
      @update:model-value="$emit('update:date', $event)"
    />
    <p
      v-else
      class="pb-2 text-xs text-muted-foreground"
    >
      今日盘中预演 · {{ date || '暂无数据' }}
    </p>
  </div>
</template>

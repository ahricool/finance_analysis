<script setup lang="ts">
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import type { ResearchDataMode } from '@/utils/researchPreview';

defineProps<{
  mode: ResearchDataMode;
  previewAvailable: boolean;
  previewHint?: string;
}>();

const emit = defineEmits<{ 'update:mode': [ResearchDataMode] }>();
</script>

<template>
  <div
    class="inline-flex flex-wrap rounded-md border"
    data-slot="button-group"
    data-testid="research-data-mode"
    role="group"
    aria-label="数据模式"
  >
    <TooltipProvider :delay-duration="150">
      <Tooltip :disabled="previewAvailable">
        <TooltipTrigger as-child>
          <span class="inline-flex">
            <Button
              type="button"
              size="lg"
              class="h-10 rounded-r-none border-0"
              :variant="mode === 'preview' ? 'secondary' : 'ghost'"
              :disabled="!previewAvailable"
              :aria-pressed="mode === 'preview'"
              data-testid="research-mode-preview"
              @click="emit('update:mode', 'preview')"
            >
              盘中预演
            </Button>
          </span>
        </TooltipTrigger>
        <TooltipContent v-if="!previewAvailable">
          {{ previewHint || '暂无预演' }}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
    <Button
      type="button"
      size="lg"
      class="h-10 rounded-l-none border-0 border-l"
      :variant="mode === 'official' ? 'secondary' : 'ghost'"
      :aria-pressed="mode === 'official'"
      data-testid="research-mode-official"
      @click="emit('update:mode', 'official')"
    >
      正式收盘
    </Button>
  </div>
</template>

<script setup lang="ts">
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { CircleHelp } from 'lucide-vue-next';

defineProps<{ label: string; description: string }>();
</script>

<template>
  <span class="inline-flex min-w-0 items-center gap-1">
    <span class="truncate">{{ label }}</span>
    <TooltipProvider :delay-duration="150">
      <Tooltip>
        <TooltipTrigger as-child>
          <button
            type="button"
            class="shrink-0 text-muted-foreground hover:text-foreground"
            :aria-label="`查看 ${label} 计算公式`"
            @click.stop
          >
            <CircleHelp class="size-3.5" />
          </button>
        </TooltipTrigger>
        <TooltipContent class="max-w-72 whitespace-normal text-left leading-5">
          {{ description }}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  </span>
</template>

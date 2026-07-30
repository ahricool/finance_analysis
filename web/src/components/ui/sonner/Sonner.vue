<script lang="ts" setup>
import type { ToasterProps } from 'vue-sonner'

import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
  XIcon,
} from 'lucide-vue-next'
import { reactiveOmit } from '@vueuse/core'
import { Toaster as Sonner } from 'vue-sonner'
import { cn } from '@/utils/cn'

const props = defineProps<ToasterProps>()
const delegatedProps = reactiveOmit(props, 'class', 'toastOptions')
</script>

<template>
  <Sonner
    :class="cn('toaster group', props.class)"
    :style="{
      '--normal-bg': 'hsl(var(--popover))',
      '--normal-text': 'hsl(var(--popover-foreground))',
      '--normal-border': 'hsl(var(--border))',
      '--border-radius': 'var(--radius)',
      '--gray2': 'hsl(var(--popover) / 0.9)',
      '--gray3': 'hsl(var(--border))',
      '--gray4': 'hsl(var(--border))',
      '--gray5': 'hsl(var(--border))',
      '--gray12': 'hsl(var(--popover-foreground))',
    }"
    :toast-options="props.toastOptions ?? {
      classes: {
        toast: 'rounded-2xl',
      },
    }"
    v-bind="delegatedProps"
  >
    <template #success-icon>
      <CircleCheckIcon class="size-4" />
    </template>
    <template #info-icon>
      <InfoIcon class="size-4" />
    </template>
    <template #warning-icon>
      <TriangleAlertIcon class="size-4" />
    </template>
    <template #error-icon>
      <OctagonXIcon class="size-4" />
    </template>
    <template #loading-icon>
      <div>
        <Loader2Icon class="size-4 animate-spin" />
      </div>
    </template>
    <template #close-icon>
      <XIcon class="size-4" />
    </template>
  </Sonner>
</template>

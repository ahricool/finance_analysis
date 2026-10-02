<script setup lang="ts">
import { computed } from 'vue';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { CircleHelp } from 'lucide-vue-next';
import { enumLabel, metricLabel, type Bilingual } from '@/i18n/labels';

const props = withDefaults(defineProps<{
  /** Glossary key from metricLabels, or raw Chinese. */
  label?: string;
  zh?: string;
  en?: string;
  /** Look up enumLabels for business enums (API value unchanged). */
  enumValue?: string | null;
  /** Table-header compact: Chinese only; English in native title / tooltip. */
  compact?: boolean;
  /** Stack English under Chinese (default) or inline. */
  inline?: boolean;
  description?: string;
  wrap?: boolean;
}>(), {
  compact: false,
  inline: false,
  wrap: false,
});

const pair = computed<Bilingual>(() => {
  if (props.enumValue != null && props.enumValue !== '') return enumLabel(props.enumValue);
  if (props.zh != null || props.en != null) return { zh: props.zh || '', en: props.en || '' };
  if (props.label) return metricLabel(props.label);
  return { zh: '', en: '' };
});

const aria = computed(() => {
  const { zh, en } = pair.value;
  return en && en !== zh ? `${zh}（${en}）` : zh;
});
</script>

<template>
  <span
    class="inline-flex min-w-0 items-start gap-1"
    :class="compact ? 'max-w-full' : ''"
    :title="compact && pair.en ? pair.en : undefined"
    :aria-label="aria"
    data-slot="bilingual-label"
  >
    <span
      class="min-w-0"
      :class="inline ? 'inline-flex flex-wrap items-baseline gap-x-1.5' : 'flex flex-col gap-0.5'"
    >
      <span :class="wrap ? 'whitespace-normal break-words' : 'truncate'">{{ pair.zh }}</span>
      <span
        v-if="pair.en && !compact && pair.en !== pair.zh"
        class="text-[0.7em] font-normal tracking-wide text-muted-foreground"
        :class="wrap ? 'whitespace-normal break-words' : 'truncate'"
      >{{ pair.en }}</span>
    </span>
    <TooltipProvider
      v-if="description || (compact && pair.en)"
      :delay-duration="150"
    >
      <Tooltip>
        <TooltipTrigger as-child>
          <button
            v-if="description"
            type="button"
            class="shrink-0 text-muted-foreground hover:text-foreground"
            :aria-label="`查看 ${pair.zh} 说明`"
            @click.stop
          >
            <CircleHelp class="size-3.5" />
          </button>
          <span
            v-else
            class="sr-only"
          >{{ pair.en }}</span>
        </TooltipTrigger>
        <TooltipContent class="max-w-[min(24rem,calc(100vw-1rem))] whitespace-normal text-left leading-5">
          <template v-if="description">
            {{ description }}
          </template>
          <template v-else>
            {{ pair.en }}
          </template>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  </span>
</template>

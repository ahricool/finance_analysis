<script setup lang="ts">
import { computed } from 'vue';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger, TooltipProvider } from '@/components/ui/tooltip';
import { recentDailyStructures, structureStatusLabel, type DailyStructureEvent } from '@/utils/dailyStructures';

const props = defineProps<{ events: DailyStructureEvent[]; cutoff: string;
  selected: DailyStructureEvent | null; hovered: DailyStructureEvent | null }>();
const emit = defineEmits<{ select: [event: DailyStructureEvent | null] }>();
const recent = computed(() => recentDailyStructures(props.events, props.cutoff));
const active = computed(() => props.hovered ?? props.selected ?? recent.value[0]);
</script>

<template>
  <TooltipProvider :delay-duration="150">
    <section
      class="mt-3 border-t pt-3 text-sm"
      data-testid="daily-structure-summary"
      aria-label="结构形态"
    >
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h4 class="font-medium">
          结构形态
        </h4>
        <span class="text-xs text-muted-foreground">◆ 悬停查看 · 点击显示关键边界 · Quality 非胜率</span>
      </div>
      <p
        v-if="!recent.length"
        class="mt-2 text-muted-foreground"
      >
        最近 20 根日 K 内没有新的高质量结构事件
      </p>
      <div class="mt-2 flex flex-wrap gap-2">
        <Tooltip
          v-for="event in recent"
          :key="event.id"
        >
          <TooltipTrigger as-child>
            <Button
              size="sm"
              :variant="selected?.id === event.id ? 'secondary' : 'ghost'"
              :aria-pressed="selected?.id === event.id"
              @click="emit('select', event)"
            >
              {{ event.date.slice(5) }} {{ event.name }} · {{ structureStatusLabel(event) }}
            </Button>
          </TooltipTrigger>
          <TooltipContent class="max-w-xs">
            {{ event.reasons[0] }} · Quality {{ event.quality }}
          </TooltipContent>
        </Tooltip>
        <Button
          v-if="selected"
          size="sm"
          variant="ghost"
          @click="emit('select', null)"
        >
          隐藏边界
        </Button>
      </div>
      <div
        v-if="active"
        class="mt-2 rounded border p-3"
        data-testid="daily-structure-detail"
        aria-live="polite"
      >
        <div class="flex flex-wrap items-center gap-2">
          <strong :class="active.direction === 'bullish' ? 'text-market-up' : active.direction === 'bearish' ? 'text-market-down' : 'text-muted-foreground'">
            {{ active.name }}
          </strong>
          <span>{{ active.date }} · {{ structureStatusLabel(active) }} · Quality {{ active.quality }}</span>
        </div>
        <p class="mt-1 text-xs text-muted-foreground">
          结构开始 {{ active.startDate }} · {{ active.barConfirmed ? '已完成日 K' : '未取得收盘确认' }}
        </p>
        <div class="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span
            v-for="line in active.lines"
            :key="line.name"
          >{{ line.name }} {{ line.endValue.toFixed(2) }}</span>
        </div>
        <ul class="mt-2 list-inside list-disc text-xs leading-5 text-muted-foreground">
          <li
            v-for="reason in active.reasons"
            :key="reason"
          >
            {{ reason }}
          </li>
        </ul>
      </div>
      <details
        v-if="events.length"
        class="mt-2 text-xs text-muted-foreground"
      >
        <summary class="cursor-pointer">
          历史结构事件（{{ events.length }}）
        </summary>
        <div class="mt-2 flex max-h-40 flex-wrap gap-1 overflow-y-auto">
          <Button
            v-for="event in [...events].reverse()"
            :key="event.id"
            size="sm"
            variant="ghost"
            @click="emit('select', event)"
          >
            {{ event.date }} {{ event.name }} · {{ structureStatusLabel(event) }}
          </Button>
        </div>
      </details>
    </section>
  </TooltipProvider>
</template>

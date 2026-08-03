<script setup lang="ts">
import { Check, Clock3 } from 'lucide-vue-next';
import { computed } from 'vue';
import { storeToRefs } from 'pinia';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { DISPLAY_TIMEZONES, type DisplayTimezone, useTimezoneStore } from '@/stores/timezoneStore';

const store = useTimezoneStore();
const { displayTimezone } = storeToRefs(store);
const activeOption = computed(
  () => DISPLAY_TIMEZONES.find((option) => option.value === displayTimezone.value) ?? DISPLAY_TIMEZONES[0],
);

function setTimezone(value: DisplayTimezone) {
  store.setDisplayTimezone(value);
}
</script>

<template>
  <DropdownMenu :modal="false">
    <DropdownMenuTrigger as-child>
      <Button
        variant="ghost"
        size="sm"
        aria-label="切换展示时区"
        class="gap-1 text-muted-foreground"
      >
        <Clock3 />
        <span class="hidden sm:inline">{{ activeOption.shortLabel }}</span>
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end" class="w-64">
      <DropdownMenuLabel>
        <span class="block">展示时区</span>
        <span class="font-normal text-muted-foreground">日期与时间将按所选时区显示</span>
      </DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuItem
        v-for="option in DISPLAY_TIMEZONES"
        :key="option.value"
        class="justify-between"
        @select="setTimezone(option.value)"
      >
        <span>
          <span class="block">{{ option.label }}</span>
          <span class="block text-xs text-muted-foreground">{{ option.value }}</span>
        </span>
        <Check v-if="displayTimezone === option.value" />
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>

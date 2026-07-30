<script setup lang="ts">
import { Clock3 } from 'lucide-vue-next';
import { computed } from 'vue';
import { storeToRefs } from 'pinia';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { DISPLAY_TIMEZONES, useTimezoneStore } from '@/stores/timezoneStore';

const store = useTimezoneStore();
const { displayTimezone } = storeToRefs(store);

const activeOption = computed(
  () =>
    DISPLAY_TIMEZONES.find((option) => option.value === displayTimezone.value) ??
    DISPLAY_TIMEZONES[0],
);

function onSelect(value: unknown) {
  const match = DISPLAY_TIMEZONES.find((option) => option.value === value);
  if (match) store.setDisplayTimezone(match.value);
}
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger as-child>
      <Button
        variant="ghost"
        size="sm"
        aria-label="切换展示时区"
        class="gap-1.5 text-muted-foreground"
      >
        <Clock3 class="size-4" />
        <span class="font-mono text-xs">{{ activeOption.shortLabel }}</span>
      </Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent
      align="end"
      class="w-52"
    >
      <DropdownMenuLabel>展示时区</DropdownMenuLabel>
      <DropdownMenuSeparator />
      <DropdownMenuRadioGroup
        :model-value="displayTimezone"
        @update:model-value="onSelect"
      >
        <DropdownMenuRadioItem
          v-for="option in DISPLAY_TIMEZONES"
          :key="option.value"
          :value="option.value"
          class="cursor-pointer"
        >
          <span class="flex flex-col">
            <span>{{ option.label }}</span>
            <span class="font-mono text-xs text-muted-foreground">{{ option.value }}</span>
          </span>
        </DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
    </DropdownMenuContent>
  </DropdownMenu>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, useId } from 'vue';
import { CircleHelp } from 'lucide-vue-next';
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover';

const props = defineProps<{ label: string; description: string }>();
const open = ref(false);
const pinned = ref(false);
const trigger = ref<HTMLButtonElement | null>(null);
const id = useId();
let closeTimer: ReturnType<typeof setTimeout> | undefined;

function cancelClose() { clearTimeout(closeTimer); }
function show() { cancelClose(); open.value = true; }
function dismiss() { cancelClose(); open.value = false; pinned.value = false; }
function leave() {
  cancelClose();
  closeTimer = setTimeout(() => {
    if (!pinned.value && document.activeElement !== trigger.value) open.value = false;
  }, 150);
}
function onInteractOutside(event: CustomEvent<{ originalEvent: Event }>) {
  // The external anchor keeps closed help lightweight in large metric tables.
  // Anchor does not register a Reka trigger. Keep its pointerdown/focus from
  // dismissing the layer before our click handler can toggle the pinned state.
  const target = event.detail.originalEvent.target;
  if (target instanceof Node && trigger.value?.contains(target)) event.preventDefault();
}
function toggle() {
  if (pinned.value) dismiss();
  else { pinned.value = true; show(); }
}
function escape(event: KeyboardEvent) {
  if (!open.value) return;
  event.preventDefault();
  event.stopPropagation();
  // The hint is the innermost layer; Escape must not also dismiss a stock dialog.
  trigger.value?.focus();
  dismiss();
}
onBeforeUnmount(cancelClose);
</script>

<template>
  <button
    ref="trigger"
    type="button"
    class="inline-flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    :aria-label="`查看 ${props.label} 说明`"
    aria-haspopup="dialog"
    :aria-expanded="open"
    :aria-controls="open ? id : undefined"
    :aria-describedby="open ? `${id}-description` : undefined"
    data-slot="metric-hint-trigger"
    @pointerenter="event => { if (event.pointerType !== 'touch') show(); }"
    @pointerleave="leave"
    @focus="show"
    @blur="leave"
    @click.stop="toggle"
    @keydown.esc="escape"
  >
    <CircleHelp
      class="size-3.5"
      aria-hidden="true"
    />
  </button>
  <Popover
    v-if="open"
    :open="open"
    @update:open="value => { if (!value) dismiss(); }"
  >
    <PopoverAnchor
      as="span"
      class="hidden"
      :reference="trigger ?? undefined"
    />
    <PopoverContent
      :id="id"
      :aria-label="`${props.label}说明`"
      :aria-describedby="`${id}-description`"
      class="max-h-[min(28rem,70dvh)] w-96 max-w-[calc(100vw-1rem)] overflow-y-auto whitespace-pre-line text-left text-sm leading-6"
      :collision-padding="8"
      @open-auto-focus.prevent
      @close-auto-focus.prevent
      @escape-key-down="escape"
      @interact-outside="onInteractOutside"
      @pointerenter="cancelClose"
      @pointerleave="leave"
      @click.stop
    >
      <span :id="`${id}-description`">{{ description }}</span>
    </PopoverContent>
  </Popover>
</template>

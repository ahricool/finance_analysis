<script setup lang="ts">
withDefaults(
  defineProps<{
    isOpen: boolean;
    title: string;
    message: string;
    confirmText?: string;
    cancelText?: string;
    isDanger?: boolean;
  }>(),
  {
    confirmText: '确定',
    cancelText: '取消',
    isDanger: false,
  },
);

const emit = defineEmits<{
  confirm: [];
  cancel: [];
}>();
</script>

<template>
  <Teleport to="body">
    <div
      v-if="isOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm transition-all"
      @click="emit('cancel')"
    >
      <div
        class="mx-4 w-full max-w-sm rounded-xl border border-border/70 bg-elevated p-6 shadow-2xl animate-in fade-in zoom-in duration-200"
        @click.stop
      >
        <h3 class="mb-2 text-lg font-medium text-foreground">{{ title }}</h3>
        <p class="mb-6 text-sm leading-relaxed text-secondary-text">
          {{ message }}
        </p>
        <div class="flex justify-end gap-3">
          <button
            type="button"
            class="rounded-lg border border-border/70 px-4 py-2 text-sm font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
            @click="emit('cancel')"
          >
            {{ cancelText }}
          </button>
          <button
            type="button"
            :class="
              isDanger
                ? 'rounded-lg bg-red-500/80 px-4 py-2 text-sm font-medium text-foreground shadow-lg shadow-red-500/20 transition-colors hover:bg-red-500'
                : 'rounded-lg bg-cyan/80 px-4 py-2 text-sm font-medium text-foreground shadow-lg shadow-cyan/20 transition-colors hover:bg-cyan'
            "
            @click="emit('confirm')"
          >
            {{ confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

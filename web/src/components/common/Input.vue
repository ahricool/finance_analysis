<script setup lang="ts">
import EyeToggleIcon from '@/components/common/EyeToggleIcon.vue';
import { cn } from '@/utils/cn';
import { Key, Lock, Mail } from 'lucide-vue-next';
import { computed, getCurrentInstance, ref, useId } from 'vue';

defineOptions({ inheritAttrs: false });

const props = withDefaults(
  defineProps<{
    label?: string;
    hint?: string;
    error?: string;
    id?: string;
    name?: string;
    class?: string;
    appearance?: 'default' | 'login';
    allowTogglePassword?: boolean;
    iconType?: 'password' | 'key' | 'mail' | 'none';
    /** Controlled password visibility */
    passwordVisible?: boolean;
    type?: string;
  }>(),
  {
    appearance: 'default',
    iconType: 'none',
    type: 'text',
    class: '',
  },
);

const emit = defineEmits<{
  'update:passwordVisible': [visible: boolean];
}>();

const generatedId = useId();
const inputId = computed(() => props.id ?? props.name ?? generatedId);
const hintId = computed(() => (props.hint ? `${inputId.value}-hint` : undefined));
const errorId = computed(() => (props.error ? `${inputId.value}-error` : undefined));

const describedBy = computed(() => {
  const parts = [hintId.value, errorId.value].filter(Boolean);
  return parts.length ? parts.join(' ') : undefined;
});

const isPasswordVisibleInner = ref(false);
const isPasswordInput = computed(() => props.type === 'password');
const instance = getCurrentInstance();
const isVisibilityControlled = computed(() => {
  const vnodeProps = instance?.vnode.props;
  return Boolean(vnodeProps && ('passwordVisible' in vnodeProps || 'password-visible' in vnodeProps));
});
const isLoginAppearance = computed(() => props.appearance === 'login');
const visible = computed(() =>
  isVisibilityControlled.value ? props.passwordVisible! : isPasswordVisibleInner.value,
);
const effectiveType = computed(() =>
  isPasswordInput.value && props.allowTogglePassword && visible.value ? 'text' : props.type,
);

const inputStyle = computed(() =>
  props.error
    ? {
        '--input-surface-border-focus': 'hsla(var(--destructive), 0.4)',
        '--input-surface-focus-ring': '0 0 0 4px hsla(var(--destructive), 0.1)',
      }
    : undefined,
);

function togglePassword() {
  const nextVisible = !visible.value;
  if (!isVisibilityControlled.value) {
    isPasswordVisibleInner.value = nextVisible;
  }
  emit('update:passwordVisible', nextVisible);
}
</script>

<template>
  <div :class="cn('flex flex-col', props.class)">
    <label
      v-if="label"
      :for="inputId"
      :class="
        cn(
          'mb-2 text-sm font-medium',
          isLoginAppearance ? 'text-[var(--login-label-text)]' : 'text-foreground',
        )
      "
    >
      {{ label }}
    </label>
    <div class="relative flex items-center">
      <div v-if="iconType === 'password'" class="pointer-events-none absolute left-3.5 z-10">
        <Lock
          :class="
            cn(
              'h-4 w-4',
              isLoginAppearance ? 'text-[var(--login-input-icon)]' : 'text-muted-text/55',
            )
          "
        />
      </div>
      <div v-else-if="iconType === 'key'" class="pointer-events-none absolute left-3.5 z-10">
        <Key
          :class="
            cn(
              'h-4 w-4',
              isLoginAppearance ? 'text-[var(--login-input-icon)]' : 'text-muted-text/55',
            )
          "
        />
      </div>
      <div v-else-if="iconType === 'mail'" class="pointer-events-none absolute left-3.5 z-10">
        <Mail
          :class="
            cn(
              'h-4 w-4',
              isLoginAppearance ? 'text-[var(--login-input-icon)]' : 'text-muted-text/55',
            )
          "
        />
      </div>
      <input
        :id="inputId"
        v-bind="$attrs"
        :name="name"
        :type="effectiveType"
        :aria-describedby="describedBy"
        :aria-invalid="error ? true : undefined"
        :style="inputStyle ?? undefined"
        :data-appearance="appearance"
        :class="
          cn(
            'input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-4 text-sm transition-all',
            'focus:outline-none',
            isLoginAppearance ? 'input-appearance-login' : '',
            error ? 'border-danger/30' : '',
            iconType !== 'none' ? 'pl-10' : '',
            (isPasswordInput && allowTogglePassword) || $slots.trailing ? 'pr-12' : '',
            'disabled:cursor-not-allowed disabled:opacity-60',
          )
        "
      />
      <div
        v-if="isPasswordInput && allowTogglePassword"
        class="absolute inset-y-0 right-2 z-20 flex items-center"
      >
        <button
          type="button"
          :class="
            cn(
              'inline-flex h-8 w-8 items-center justify-center rounded-lg border transition-all duration-200 focus:outline-none focus:ring-2',
              isLoginAppearance
                ? visible
                  ? 'border-[var(--login-input-toggle-active-border)] bg-[var(--login-input-toggle-active-bg)] text-[var(--login-input-toggle-active-text)] shadow-[0_0_14px_var(--login-accent-glow)] focus:ring-[var(--login-input-toggle-ring)]'
                  : 'border-[var(--login-input-toggle-border)] bg-[var(--login-input-toggle-bg)] text-[var(--login-input-toggle-text)] hover:border-[var(--login-input-toggle-border-hover)] hover:bg-[var(--login-input-toggle-bg-hover)] hover:text-[var(--login-input-toggle-text-hover)] focus:ring-[var(--login-input-toggle-ring)]'
                : visible
                  ? 'border-warning/40 bg-warning/15 text-warning shadow-[0_0_10px_hsla(var(--warning),0.15)]'
                  : 'border-border/40 bg-muted/20 text-muted-text hover:border-warning/40 hover:text-warning hover:shadow-[0_0_10px_hsla(var(--warning),0.15)] focus:ring-primary/30',
            )
          "
          :aria-label="visible ? '隐藏内容' : '显示内容'"
          @click="togglePassword"
        >
          <EyeToggleIcon :visible="visible" />
        </button>
      </div>
      <div
        v-else-if="$slots.trailing"
        class="absolute inset-y-0 right-2 flex items-center"
      >
        <slot name="trailing" />
      </div>
    </div>
    <p
      v-if="error"
      :id="errorId"
      role="alert"
      :class="cn('mt-2 text-xs', isLoginAppearance ? 'text-[var(--login-error-text)]' : 'text-danger')"
    >
      {{ error }}
    </p>
    <p
      v-else-if="hint"
      :id="hintId"
      :class="
        cn(
          'mt-2 text-xs',
          isLoginAppearance ? 'text-[var(--login-hint-text)]' : 'text-secondary-text',
        )
      "
    >
      {{ hint }}
    </p>
  </div>
</template>

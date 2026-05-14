<script setup lang="ts">
import { authApi } from '@/api/auth';
import { getParsedApiError, isParsedApiError, type ParsedApiError } from '@/api/error';
import Badge from '@/components/common/Badge.vue';
import Button from '@/components/common/Button.vue';
import Checkbox from '@/components/common/Checkbox.vue';
import Input from '@/components/common/Input.vue';
import SettingsAlert from '@/components/settings/SettingsAlert.vue';
import SettingsSectionCard from '@/components/settings/SettingsSectionCard.vue';
import { useAuth } from '@/composables/useAuth';
import { computed, ref, watch } from 'vue';

function createNextModeLabel(authEnabled: boolean, desiredEnabled: boolean) {
  if (authEnabled && !desiredEnabled) {
    return '关闭认证';
  }
  if (!authEnabled && desiredEnabled) {
    return '开启认证';
  }
  return authEnabled ? '保持已开启' : '保持已关闭';
}

const { authEnabled, setupState, refreshStatus } = useAuth();

const desiredEnabled = ref(authEnabled.value);
const currentPassword = ref('');
const password = ref('');
const passwordConfirm = ref('');
const isSubmitting = ref(false);
const error = ref<string | ParsedApiError | null>(null);
const successMessage = ref<string | null>(null);

watch(
  authEnabled,
  (v) => {
    desiredEnabled.value = v;
  },
  { immediate: true },
);

const isDirty = computed(
  () =>
    desiredEnabled.value !== authEnabled.value
    || !!currentPassword.value
    || !!password.value
    || !!passwordConfirm.value,
);

const targetActionLabel = computed(() => createNextModeLabel(authEnabled.value, desiredEnabled.value));

const helperText = computed(() => {
  switch (setupState.value) {
    case 'no_password':
      return '系统尚未设置密码。启用认证前请先设置初始管理员密码，设置后请妥善保管。';
    case 'password_retained':
      return '系统已保留之前设置的管理员密码。输入当前密码即可快速重新启用认证。';
    case 'enabled':
      return !desiredEnabled.value
        ? '若当前登录会话仍有效，可直接关闭认证；若会话已失效，请输入当前管理员密码。'
        : '管理员认证已启用。如需更新密码，请使用下方的“修改密码”功能。';
    default:
      return '管理员认证可保护 Web 设置页及 API 接口，防止未经授权的访问。';
  }
});

function resetForm() {
  currentPassword.value = '';
  password.value = '';
  passwordConfirm.value = '';
}

async function handleSubmit(event: Event) {
  event.preventDefault();
  error.value = null;
  successMessage.value = null;

  if (setupState.value === 'no_password' && desiredEnabled.value) {
    if (!password.value) {
      error.value = '设置新密码是必填项';
      return;
    }
    if (password.value !== passwordConfirm.value) {
      error.value = '两次输入的新密码不一致';
      return;
    }
  }

  isSubmitting.value = true;
  try {
    await authApi.updateSettings(
      desiredEnabled.value,
      password.value.trim() || undefined,
      passwordConfirm.value.trim() || undefined,
      currentPassword.value.trim() || undefined,
    );
    await refreshStatus();
    successMessage.value = desiredEnabled.value ? '认证设置已更新' : '认证已关闭';
    resetForm();
  } catch (err: unknown) {
    error.value = getParsedApiError(err);
  } finally {
    isSubmitting.value = false;
  }
}

function onReset() {
  desiredEnabled.value = authEnabled.value;
  error.value = null;
  successMessage.value = null;
  resetForm();
}
</script>

<template>
  <SettingsSectionCard
    title="认证与登录保护"
    description="管理管理员密码认证，保护您的系统配置安全。"
  >
    <template #actions>
      <Badge
        :variant="authEnabled ? 'success' : 'default'"
        size="sm"
        :class="
          authEnabled ? '' : 'border-[var(--settings-border)] bg-[var(--settings-surface-hover)] text-secondary-text'
        "
      >
        {{ authEnabled ? '已启用' : '未启用' }}
      </Badge>
    </template>

    <form class="space-y-4" @submit="handleSubmit">
      <div
        class="rounded-xl border border-[var(--settings-border)] bg-[var(--settings-surface)] p-4 shadow-soft-card transition-[background-color,border-color] duration-200 hover:border-[var(--settings-border-strong)] hover:bg-[var(--settings-surface-hover)]"
      >
        <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div class="space-y-1">
            <p class="text-sm font-semibold text-foreground">管理员认证</p>
            <p class="text-xs leading-6 text-muted-text">{{ helperText }}</p>
          </div>
          <Checkbox
            :checked="desiredEnabled"
            :disabled="isSubmitting"
            :label="desiredEnabled ? '开启' : '关闭'"
            container-class="rounded-full border border-[var(--settings-border)] bg-[var(--settings-surface-hover)] px-4 py-2 shadow-soft-card transition-[background-color,border-color] duration-200 hover:border-[var(--settings-border-strong)] hover:bg-[var(--settings-surface)]"
            @change="desiredEnabled = ($event.target as HTMLInputElement).checked"
          />
        </div>
      </div>

      <div
        v-if="desiredEnabled || (authEnabled && !desiredEnabled)"
        class="grid gap-4 md:grid-cols-2"
      >
        <div
          v-if="
            (setupState === 'password_retained' && desiredEnabled)
              || (setupState === 'enabled' && !desiredEnabled)
          "
          class="space-y-3"
        >
          <Input
            label="当前管理员密码"
            type="password"
            allow-toggle-password
            icon-type="password"
            :value="currentPassword"
            autocomplete="current-password"
            :disabled="isSubmitting"
            placeholder="请输入当前密码"
            :hint="
              setupState === 'password_retained' ? '输入旧密码以重新激活认证' : '关闭认证前可能需要验证身份'
            "
            @input="currentPassword = ($event.target as HTMLInputElement).value"
          />
        </div>

        <template v-if="setupState === 'no_password' && desiredEnabled">
          <div class="space-y-3">
            <Input
              label="设置管理员密码"
              type="password"
              allow-toggle-password
              icon-type="password"
              :value="password"
              autocomplete="new-password"
              :disabled="isSubmitting"
              placeholder="输入新密码 (至少 6 位)"
              @input="password = ($event.target as HTMLInputElement).value"
            />
          </div>
          <div class="space-y-3">
            <Input
              label="确认新密码"
              type="password"
              allow-toggle-password
              icon-type="password"
              :value="passwordConfirm"
              autocomplete="new-password"
              :disabled="isSubmitting"
              placeholder="再次输入以确认"
              @input="passwordConfirm = ($event.target as HTMLInputElement).value"
            />
          </div>
        </template>
      </div>

      <SettingsAlert
        v-if="error && isParsedApiError(error)"
        title="认证设置失败"
        :message="error.message"
        variant="error"
      />
      <SettingsAlert
        v-else-if="error"
        title="认证设置失败"
        :message="String(error)"
        variant="error"
      />

      <SettingsAlert
        v-if="successMessage"
        title="操作成功"
        :message="successMessage"
        variant="success"
      />

      <div class="flex flex-wrap items-center gap-2">
        <Button type="submit" variant="settings-primary" :is-loading="isSubmitting" :disabled="!isDirty">
          {{ targetActionLabel }}
        </Button>
        <Button type="button" variant="settings-secondary" :disabled="isSubmitting || !isDirty" @click="onReset">
          还原
        </Button>
      </div>
    </form>
  </SettingsSectionCard>
</template>

<script setup lang="ts">
import { isParsedApiError } from '@/api/error';
import type { ParsedApiError } from '@/api/error';
import Button from '@/components/common/Button.vue';
import Input from '@/components/common/Input.vue';
import SettingsAlert from '@/components/settings/SettingsAlert.vue';
import SettingsSectionCard from '@/components/settings/SettingsSectionCard.vue';
import { useAuth } from '@/composables/useAuth';
import { ref } from 'vue';

const { changePassword } = useAuth();

const currentPassword = ref('');
const newPassword = ref('');
const newPasswordConfirm = ref('');
const isSubmitting = ref(false);
const error = ref<string | ParsedApiError | null>(null);
const success = ref(false);

async function handleSubmit(e: Event) {
  e.preventDefault();
  error.value = null;
  success.value = false;

  if (!currentPassword.value.trim()) {
    error.value = '请输入当前密码';
    return;
  }
  if (!newPassword.value.trim()) {
    error.value = '请输入新密码';
    return;
  }
  if (newPassword.value.length < 6) {
    error.value = '新密码至少 6 位';
    return;
  }
  if (newPassword.value !== newPasswordConfirm.value) {
    error.value = '两次输入的新密码不一致';
    return;
  }

  isSubmitting.value = true;
  try {
    const result = await changePassword(currentPassword.value, newPassword.value, newPasswordConfirm.value);
    if (result.success) {
      success.value = true;
      currentPassword.value = '';
      newPassword.value = '';
      newPasswordConfirm.value = '';
      window.setTimeout(() => {
        success.value = false;
      }, 4000);
    } else {
      error.value = result.error?.message ?? '修改失败';
    }
  } finally {
    isSubmitting.value = false;
  }
}
</script>

<template>
  <SettingsSectionCard
    title="修改密码"
  >
    <form class="space-y-4" @submit="handleSubmit">
      <Input
        id="change-pass-current"
        type="password"
        allow-toggle-password
        icon-type="password"
        label="当前密码"
        class="max-w-sm"
        placeholder="输入当前密码"
        :value="currentPassword"
        :disabled="isSubmitting"
        autocomplete="current-password"
        @input="currentPassword = ($event.target as HTMLInputElement).value"
      />

      <Input
        id="change-pass-new"
        type="password"
        allow-toggle-password
        icon-type="password"
        label="新密码"
        class="max-w-sm"
        placeholder="输入新密码"
        :value="newPassword"
        :disabled="isSubmitting"
        autocomplete="new-password"
        @input="newPassword = ($event.target as HTMLInputElement).value"
      />

      <div>
        <Input
          id="change-pass-confirm"
          type="password"
          allow-toggle-password
          icon-type="password"
          label="确认新密码"
          class="max-w-sm"
          placeholder="再次输入新密码"
          :value="newPasswordConfirm"
          :disabled="isSubmitting"
          autocomplete="new-password"
          @input="newPasswordConfirm = ($event.target as HTMLInputElement).value"
        />
      </div>

      <SettingsAlert
        v-if="error && isParsedApiError(error)"
        title="修改失败"
        :message="error.message"
        variant="error"
        class="!mt-3"
      />
      <SettingsAlert
        v-else-if="error"
        title="修改失败"
        :message="String(error)"
        variant="error"
        class="!mt-3"
      />
      <SettingsAlert
        v-if="success"
        title="修改成功"
        message="登录密码已更新。"
        variant="success"
      />

      <Button type="submit" variant="primary" :is-loading="isSubmitting">保存新密码</Button>
    </form>
  </SettingsSectionCard>
</template>

<script setup lang="ts">
import { isParsedApiError } from '@/api/error';
import type { ParsedApiError } from '@/api/error';
import LoadingButton from '@/components/app/LoadingButton.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
    const result = await changePassword(
      currentPassword.value,
      newPassword.value,
      newPasswordConfirm.value,
    );
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
  <Card>
    <CardHeader>
      <CardTitle>修改密码</CardTitle>
    </CardHeader>
    <CardContent>
      <form
        class="space-y-4"
        @submit="handleSubmit"
      >
        <FieldInput
          id="change-pass-current"
          v-model="currentPassword"
          type="password"
          allow-toggle-password
          label="当前密码"
          class="max-w-sm"
          placeholder="输入当前密码"
          :disabled="isSubmitting"
          autocomplete="current-password"
        />

        <FieldInput
          id="change-pass-new"
          v-model="newPassword"
          type="password"
          allow-toggle-password
          label="新密码"
          class="max-w-sm"
          placeholder="输入新密码"
          :disabled="isSubmitting"
          autocomplete="new-password"
        />

        <FieldInput
          id="change-pass-confirm"
          v-model="newPasswordConfirm"
          type="password"
          allow-toggle-password
          label="确认新密码"
          class="max-w-sm"
          placeholder="再次输入新密码"
          :disabled="isSubmitting"
          autocomplete="new-password"
        />

        <Alert
          v-if="error"
          variant="destructive"
        >
          <AlertTitle>修改失败</AlertTitle>
          <AlertDescription>
            {{ isParsedApiError(error) ? error.message : String(error) }}
          </AlertDescription>
        </Alert>
        <Alert
          v-if="success"
          variant="success"
        >
          <AlertTitle>修改成功</AlertTitle>
          <AlertDescription>登录密码已更新。</AlertDescription>
        </Alert>

        <LoadingButton
          type="submit"
          variant="default"
          :loading="isSubmitting"
        >
          保存新密码
        </LoadingButton>
      </form>
    </CardContent>
  </Card>
</template>

<script setup lang="ts">
import { isParsedApiError, type ParsedApiError } from '@/api/error';
import LoadingButton from '@/components/app/LoadingButton.vue';
import SettingsAlert from '@/components/settings/SettingsAlert.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/composables/useAuth';
import { APP_NAME } from '@/config/app';
import { Lock } from 'lucide-vue-next';
import { computed, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

type LoginStep = 'email' | 'password' | 'setup';

const { lookupEmail, setupPassword, login } = useAuth();
const router = useRouter();
const route = useRoute();

const rawRedirect = computed(() => (route.query.redirect as string) ?? '');
const redirect = computed(() =>
  rawRedirect.value.startsWith('/') && !rawRedirect.value.startsWith('//')
    ? rawRedirect.value
    : '/analysis',
);

const step = ref<LoginStep>('email');
const email = ref('');
const password = ref('');
const passwordConfirm = ref('');
const isSubmitting = ref(false);
const error = ref<string | ParsedApiError | null>(null);
const setupSuccessMessage = ref<string | null>(null);

const stepTitle = computed(() => {
  if (step.value === 'email') return '用户登录';
  if (step.value === 'setup') return '设置登录密码';
  return '输入密码';
});

const submitLabel = computed(() => {
  if (step.value === 'email') return '继续';
  if (step.value === 'setup') return '设置密码';
  return '登录';
});

const loadingText = computed(() => {
  if (step.value === 'email') return '正在验证...';
  if (step.value === 'setup') return '正在设置...';
  return '正在登录...';
});

function resetToEmailStep() {
  step.value = 'email';
  password.value = '';
  passwordConfirm.value = '';
}

async function handleSubmit(e: Event) {
  e.preventDefault();
  error.value = null;
  setupSuccessMessage.value = null;
  isSubmitting.value = true;

  try {
    const trimmedEmail = email.value.trim();
    if (!trimmedEmail) {
      error.value = '请输入邮箱';
      return;
    }

    if (step.value === 'email') {
      const lookup = await lookupEmail(trimmedEmail);
      if (!lookup.success) {
        error.value = lookup.error?.message ?? '邮箱验证失败';
        return;
      }
      email.value = trimmedEmail;
      step.value = lookup.needsPasswordSetup ? 'setup' : 'password';
      return;
    }

    if (step.value === 'setup') {
      if (!password.value || !passwordConfirm.value) {
        error.value = '请填写并确认密码';
        return;
      }
      const result = await setupPassword(trimmedEmail, password.value, passwordConfirm.value);
      if (!result.success) {
        error.value = result.error?.message ?? '设置密码失败';
        return;
      }
      setupSuccessMessage.value = '密码已设置，请使用邮箱和新密码重新登录';
      resetToEmailStep();
      return;
    }

    const result = await login(trimmedEmail, password.value);
    if (result.success) {
      await router.replace(redirect.value);
    } else {
      error.value = result.error?.message ?? '登录失败';
    }
  } finally {
    isSubmitting.value = false;
  }
}

</script>

<template>
  <div
    class="fixed inset-0 min-h-screen overflow-y-auto bg-cover bg-center bg-no-repeat"
    style="background-image: url('/background.jpg')"
  >
    <div class="absolute inset-0 bg-black/30" />
    <div class="relative grid min-h-screen place-items-center px-4 py-10 lg:grid-cols-2">
      <div class="w-full max-w-sm lg:col-start-2">
        <div class="mb-6 flex items-center gap-3">
          <span
            class="flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-white"
          >
            <img
              src="/flower.svg"
              alt=""
              class="size-10"
            />
          </span>
          <span
            class="text-2xl font-semibold tracking-tight text-white sm:text-3xl"
          >
            {{ APP_NAME }}
          </span>
        </div>

        <Card>
          <CardHeader>
            <CardTitle class="flex items-center gap-2">
              <Lock class="size-5 text-muted-foreground" />
              <span>{{ stepTitle }}</span>
            </CardTitle>
            <CardDescription>
              {{ step === 'email' ? '输入邮箱以继续访问你的金融工作台。' : email }}
            </CardDescription>
          </CardHeader>

          <form
            @submit="handleSubmit"
          >
            <CardContent class="space-y-5">
              <div class="space-y-4">
                <FieldInput
                  v-if="step === 'email'"
                  id="email"
                  v-model="email"
                  type="email"
                  label="邮箱"
                  placeholder="请输入邮箱"
                  :disabled="isSubmitting"
                  autocomplete="email"
                  data-testid="login-email"
                />

                <template v-if="step === 'password'">
                  <FieldInput
                    id="password"
                    v-model="password"
                    type="password"
                    allow-toggle-password
                    label="登录密码"
                    placeholder="请输入密码"
                    :disabled="isSubmitting"
                    autofocus
                    autocomplete="current-password"
                    data-testid="login-password"
                  />
                </template>

                <template v-if="step === 'setup'">
                  <FieldInput
                    id="password"
                    v-model="password"
                    type="password"
                    allow-toggle-password
                    label="设置密码"
                    placeholder="至少 6 位"
                    :disabled="isSubmitting"
                    autofocus
                    autocomplete="new-password"
                    data-testid="login-password"
                  />
                  <FieldInput
                    id="password-confirm"
                    v-model="passwordConfirm"
                    type="password"
                    allow-toggle-password
                    label="确认密码"
                    placeholder="再次输入密码"
                    :disabled="isSubmitting"
                    autocomplete="new-password"
                    data-testid="login-password-confirm"
                  />
                </template>
              </div>

              <div v-if="setupSuccessMessage">
                <SettingsAlert
                  title="设置成功"
                  :message="setupSuccessMessage"
                  variant="success"
                />
              </div>

              <div v-if="error">
                <SettingsAlert
                  title="验证未通过"
                  :message="isParsedApiError(error) ? error.message : String(error)"
                  variant="error"
                />
              </div>
            </CardContent>
            <CardFooter class="flex-col gap-2">
              <LoadingButton
                type="submit"
                variant="brand"
                size="lg"
                class="w-full"
                :disabled="isSubmitting"
                :loading="isSubmitting"
                :loading-text="loadingText"
                data-testid="login-submit"
              >
                {{ submitLabel }}
              </LoadingButton>

              <Button
                v-if="step !== 'email'"
                type="button"
                variant="ghost"
                class="w-full"
                :disabled="isSubmitting"
                data-testid="login-back"
                @click="resetToEmailStep"
              >
                使用其他邮箱
              </Button>
            </CardFooter>
          </form>
        </Card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { isParsedApiError, type ParsedApiError } from '@/api/error';
import Button from '@/components/common/Button.vue';
import Input from '@/components/common/Input.vue';
import SettingsAlert from '@/components/settings/SettingsAlert.vue';
import { useAuth } from '@/composables/useAuth';
import { APP_NAME, formatDocumentTitle } from '@/config/app';
import { Lock } from 'lucide-vue-next';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

type LoginStep = 'email' | 'password' | 'setup';

const { lookupEmail, setupPassword, login } = useAuth();
const router = useRouter();
const route = useRoute();

const rawRedirect = computed(() => (route.query.redirect as string) ?? '');
const redirect = computed(() =>
  rawRedirect.value.startsWith('/') && !rawRedirect.value.startsWith('//') ? rawRedirect.value : '/',
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

function onEmailInput(e: Event) {
  email.value = (e.target as HTMLInputElement).value;
}

function onPasswordInput(e: Event) {
  password.value = (e.target as HTMLInputElement).value;
}

function onPasswordConfirmInput(e: Event) {
  passwordConfirm.value = (e.target as HTMLInputElement).value;
}

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

onMounted(() => {
  document.title = formatDocumentTitle('登录');
  document.documentElement.classList.add('login-page-active');
});

onUnmounted(() => {
  document.documentElement.classList.remove('login-page-active');
});
</script>

<template>
  <div
    class="fixed inset-0 h-screen w-screen overflow-hidden bg-cover bg-center bg-no-repeat font-sans text-foreground"
    style="background-image: url('/background.png')"
  >
    <div
      class="relative grid min-h-screen w-full grid-cols-1 place-items-center px-3 py-10 sm:px-4 lg:grid-cols-2 lg:px-6"
    >
      <div class="w-full max-w-[340px] shrink-0 -translate-y-4 sm:-translate-y-6 lg:col-start-2">
        <div class="mb-6 flex items-center gap-2">
          <span
            class="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-white shadow-soft-card"
          >
            <img src="/flower.svg" alt="" class="h-8 w-8" />
          </span>
          <span class="font-display text-base leading-none text-white [text-shadow:0_1px_6px_rgb(0_0_0_/_0.35)]">{{ APP_NAME }}</span>
        </div>

        <div class="rounded-2xl border border-border/80 bg-card p-6 shadow-soft-card sm:p-7">
          <div class="mb-6">
            <h1 class="flex items-center gap-2 text-xl font-semibold tracking-tight text-foreground">
              <Lock class="h-5 w-5 text-primary" />
              <span>{{ stepTitle }}</span>
            </h1>
            <p v-if="step !== 'email'" class="mt-2 text-sm text-muted-foreground">
              {{ email }}
            </p>
          </div>

          <form class="space-y-5" @submit="handleSubmit">
            <div class="space-y-4">
              <Input
                v-if="step === 'email'"
                id="email"
                type="email"
                icon-type="mail"
                label="邮箱"
                placeholder="请输入邮箱"
                :value="email"
                :disabled="isSubmitting"
                autocomplete="email"
                data-testid="login-email"
                @input="onEmailInput"
              />

              <template v-if="step === 'password'">
                <Input
                  id="password"
                  type="password"
                  allow-toggle-password
                  icon-type="password"
                  label="登录密码"
                  placeholder="请输入密码"
                  :value="password"
                  :disabled="isSubmitting"
                  autofocus
                  autocomplete="current-password"
                  data-testid="login-password"
                  @input="onPasswordInput"
                />
              </template>

              <template v-if="step === 'setup'">
                <Input
                  id="password"
                  type="password"
                  allow-toggle-password
                  icon-type="password"
                  label="设置密码"
                  placeholder="至少 6 位"
                  :value="password"
                  :disabled="isSubmitting"
                  autofocus
                  autocomplete="new-password"
                  data-testid="login-password"
                  @input="onPasswordInput"
                />
                <Input
                  id="password-confirm"
                  type="password"
                  allow-toggle-password
                  icon-type="password"
                  label="确认密码"
                  placeholder="再次输入密码"
                  :value="passwordConfirm"
                  :disabled="isSubmitting"
                  autocomplete="new-password"
                  data-testid="login-password-confirm"
                  @input="onPasswordConfirmInput"
                />
              </template>
            </div>

            <div v-if="setupSuccessMessage" class="overflow-hidden">
              <SettingsAlert
                title="设置成功"
                :message="setupSuccessMessage"
                variant="success"
              />
            </div>

            <div v-if="error" class="animate-[loginErr_0.25s_ease-out] overflow-hidden">
              <SettingsAlert
                title="验证未通过"
                :message="isParsedApiError(error) ? error.message : String(error)"
                variant="error"
              />
            </div>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              class="h-11 w-full"
              :disabled="isSubmitting"
              :is-loading="isSubmitting"
              :loading-text="loadingText"
              data-testid="login-submit"
            >
              {{ submitLabel }}
            </Button>

            <button
              v-if="step !== 'email'"
              type="button"
              class="w-full text-center text-sm text-muted-foreground hover:text-foreground"
              :disabled="isSubmitting"
              data-testid="login-back"
              @click="resetToEmailStep"
            >
              使用其他邮箱
            </button>
          </form>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
:global(html.login-page-active) {
  overflow: hidden;
  scrollbar-gutter: auto;
}

:global(html.login-page-active body) {
  overflow: hidden;
}

@keyframes loginErr {
  from {
    opacity: 0;
    max-height: 0;
  }
  to {
    opacity: 1;
    max-height: 200px;
  }
}
</style>

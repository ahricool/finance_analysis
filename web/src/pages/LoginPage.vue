<script setup lang="ts">
import { isParsedApiError, type ParsedApiError } from '@/api/error';
import Button from '@/components/common/Button.vue';
import Input from '@/components/common/Input.vue';
import SettingsAlert from '@/components/settings/SettingsAlert.vue';
import { useAuth } from '@/composables/useAuth';
import { APP_NAME, formatDocumentTitle } from '@/config/app';
import { Lock } from 'lucide-vue-next';
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

const { login } = useAuth();
const router = useRouter();
const route = useRoute();

const rawRedirect = computed(() => (route.query.redirect as string) ?? '');
const redirect = computed(() =>
  rawRedirect.value.startsWith('/') && !rawRedirect.value.startsWith('//') ? rawRedirect.value : '/',
);

const email = ref('');
const password = ref('');
const isSubmitting = ref(false);
const error = ref<string | ParsedApiError | null>(null);

function onEmailInput(e: Event) {
  email.value = (e.target as HTMLInputElement).value;
}

function onPasswordInput(e: Event) {
  password.value = (e.target as HTMLInputElement).value;
}

onMounted(() => {
  document.title = formatDocumentTitle('登录');
});

async function handleSubmit(e: Event) {
  e.preventDefault();
  error.value = null;
  isSubmitting.value = true;
  try {
    const result = await login(password.value, email.value.trim());
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
  <div class="min-h-screen bg-background font-sans text-foreground">
    <div
      class="mx-auto flex min-h-screen w-full max-w-[1280px] items-center justify-center px-3 py-10 sm:px-4 lg:justify-end lg:px-6 lg:pr-10 xl:pr-16"
    >
      <div class="w-full max-w-[340px] shrink-0 -translate-y-4 sm:-translate-y-6">
        <div class="mb-6 flex items-center gap-2">
          <span
            class="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-white shadow-soft-card"
          >
            <img src="/flower.svg" alt="" class="h-8 w-8" />
          </span>
          <span class="font-display text-base leading-none text-black">{{ APP_NAME }}</span>
        </div>

        <div class="rounded-2xl border border-border/80 bg-card p-6 shadow-soft-card sm:p-7">
          <div class="mb-6">
            <h1 class="flex items-center gap-2 text-xl font-semibold tracking-tight text-foreground">
              <Lock class="h-5 w-5 text-primary" />
              <span>用户登录</span>
            </h1>
          </div>

          <form class="space-y-5" @submit="handleSubmit">
            <div class="space-y-4">
              <Input
                id="email"
                type="email"
                icon-type="key"
                label="邮箱"
                placeholder="请输入邮箱"
                :value="email"
                :disabled="isSubmitting"
                autocomplete="email"
                data-testid="login-email"
                @input="onEmailInput"
              />

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
              loading-text="正在登录..."
              data-testid="login-submit"
            >
              登录
            </Button>
          </form>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
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

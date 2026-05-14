<script setup lang="ts">
import { isParsedApiError } from '@/api/error';
import type { ParsedApiError } from '@/api/error';
import Button from '@/components/common/Button.vue';
import Input from '@/components/common/Input.vue';
import ParticleBackground from '@/components/common/ParticleBackground.vue';
import SettingsAlert from '@/components/settings/SettingsAlert.vue';
import { useAuth } from '@/composables/useAuth';
import { Cpu, Loader2, Lock, Network, ShieldCheck, TrendingUp } from 'lucide-vue-next';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

const { login, passwordSet, setupState } = useAuth();
const router = useRouter();
const route = useRoute();

onMounted(() => {
  document.title = '登录 - DSA';
});

const rawRedirect = computed(() => (route.query.redirect as string) ?? '');
const redirect = computed(() =>
  rawRedirect.value.startsWith('/') && !rawRedirect.value.startsWith('//') ? rawRedirect.value : '/',
);

const password = ref('');
const passwordConfirm = ref('');
const isSubmitting = ref(false);
const error = ref<string | ParsedApiError | null>(null);

const isFirstTime = computed(() => setupState.value === 'no_password' || !passwordSet.value);

const parallax = ref({ x: 0, y: 0 });

function onMouseMove(e: MouseEvent) {
  parallax.value = {
    x: e.clientX / window.innerWidth - 0.5,
    y: e.clientY / window.innerHeight - 0.5,
  };
}

onMounted(() => {
  window.addEventListener('mousemove', onMouseMove);
});

onUnmounted(() => {
  window.removeEventListener('mousemove', onMouseMove);
});

const orb1Style = computed(() => ({
  transform: `translate(${parallax.value.x * -50 + 'px'}, ${parallax.value.y * -50 + 'px'})`,
}));
const orb2Style = computed(() => ({
  transform: `translate(${parallax.value.x * 60 + 'px'}, ${parallax.value.y * 60 + 'px'})`,
}));
const logoStyle = computed(() => ({
  transform: `translate(${parallax.value.x * -8 + 'px'}, ${parallax.value.y * -8 + 'px'}) rotate(${parallax.value.x * -0.5 + 'deg'})`,
}));

async function handleSubmit(e: Event) {
  e.preventDefault();
  error.value = null;
  if (isFirstTime.value && password.value !== passwordConfirm.value) {
    error.value = '两次输入的密码不一致';
    return;
  }
  isSubmitting.value = true;
  try {
    const result = await login(password.value, isFirstTime.value ? passwordConfirm.value : undefined);
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
    class="relative flex min-h-screen flex-col justify-center overflow-hidden bg-[var(--login-bg-main)] py-12 font-sans selection:bg-[var(--login-accent-soft)] sm:px-6 lg:px-8 [perspective:1500px]"
  >
    <ParticleBackground />

    <div
      class="absolute inset-0 z-0 bg-[linear-gradient(to_right,var(--login-grid-line)_1px,transparent_1px),linear-gradient(to_bottom,var(--login-grid-line)_1px,transparent_1px)] bg-[size:24px_24px] [mask-image:var(--login-grid-mask)]"
    />

    <div
      class="absolute left-[20%] top-[20%] -z-10 h-[300px] w-[300px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--login-accent-glow)] blur-[100px]"
      :style="orb1Style"
    />
    <div
      class="absolute right-[20%] bottom-[10%] -z-10 h-[400px] w-[400px] translate-x-1/2 translate-y-1/2 rounded-full bg-emerald-600/10 blur-[120px]"
      :style="orb2Style"
    />

    <div class="relative z-10 sm:mx-auto sm:w-full sm:max-w-md">
      <div class="mb-10 flex animate-[loginFadeUp_0.5s_ease-out] flex-col items-center justify-center">
        <div
          class="pointer-events-none absolute -top-[20vh] -z-10 opacity-80"
          :style="logoStyle"
        >
          <div
            class="relative flex h-[120vh] w-[120vh] items-center justify-center rounded-full border border-[var(--login-accent-soft)] bg-gradient-to-br from-[var(--login-accent-soft)] to-[hsl(214_100%_20%_/_0.18)] shadow-[inset_0_0_200px_var(--login-accent-glow)] blur-[4px]"
          >
            <Cpu class="h-[70vh] w-[70vh] text-[hsl(200_80%_22%_/_0.4)] brightness-50" />
            <TrendingUp class="absolute h-[25vh] w-[25vh] translate-x-[15vh] translate-y-[15vh] text-emerald-900/30 brightness-50" />
          </div>
        </div>

        <div class="mt-8 flex flex-col items-center">
          <h2 class="text-4xl font-extrabold tracking-tighter text-[var(--login-text-primary)] sm:text-6xl">
            <span
              class="bg-gradient-to-r from-[var(--login-text-primary)] via-[var(--login-text-primary)] to-[var(--login-text-secondary)] bg-clip-text text-transparent"
            >
              DAILY
            </span>
            <span
              class="bg-gradient-to-r from-[var(--login-brand-start)] to-[var(--login-brand-end)] bg-clip-text text-transparent drop-shadow-[0_0_20px_var(--login-accent-glow)]"
            >
              STOCK
            </span>
          </h2>
          <h3 class="mt-1 text-xl font-bold uppercase tracking-[0.5em] text-[var(--login-text-muted)]">
            Analysis Engine
          </h3>
        </div>

        <div
          class="mt-6 flex animate-[loginFade_0.4s_ease-out_0.3s_both] items-center gap-2 rounded-full border border-[var(--login-accent-border)] bg-[var(--login-accent-soft)] px-3 py-1 text-[10px] font-medium text-[var(--login-accent-text)] backdrop-blur-sm"
        >
          <Network class="h-3 w-3" />
          <span>V3.X QUANTITATIVE SYSTEM</span>
        </div>
      </div>

      <div
        class="group pointer-events-auto relative z-20 animate-[loginScale_0.5s_ease-out_0.1s_both]"
      >
        <div
          class="pointer-events-none absolute -inset-0.5 rounded-3xl bg-gradient-to-b from-[var(--login-accent-glow)] to-[hsl(214_100%_56%_/_0.18)] opacity-50 blur-sm transition duration-1000 group-hover:opacity-100 group-hover:duration-200"
        />

        <div
          class="pointer-events-auto relative flex flex-col overflow-hidden rounded-3xl border border-[var(--login-border-card)] bg-[var(--login-bg-card)]/80 p-8 shadow-2xl backdrop-blur-xl"
        >
          <div class="absolute -right-20 -top-20 h-40 w-40 rounded-full bg-[var(--login-accent-soft)] blur-[50px]" />
          <div class="absolute -bottom-20 -left-20 h-40 w-40 rounded-full bg-blue-600/10 blur-[50px]" />

          <div class="mb-8">
            <h1 class="flex items-center gap-2 text-2xl font-bold tracking-tight text-[var(--login-text-primary)]">
              <template v-if="isFirstTime">
                <ShieldCheck class="h-6 w-6 text-emerald-400" />
                <span>设置初始密码</span>
              </template>
              <template v-else>
                <Lock class="h-5 w-5 text-[var(--login-accent-text)]" />
                <span>管理员登录</span>
              </template>
            </h1>
            <p class="mt-2 text-sm text-[var(--login-text-secondary)]">
              {{
                isFirstTime
                  ? '首次启用认证，请为系统工作台设置管理员密码。'
                  : '访问 DSA 量化决策引擎需要有效的身份凭证。'
              }}
            </p>
          </div>

          <form class="space-y-6" @submit="handleSubmit">
            <div class="space-y-4">
              <Input
                id="password"
                type="password"
                appearance="login"
                allow-toggle-password
                icon-type="password"
                :label="isFirstTime ? '管理员密码' : '登录密码'"
                :placeholder="isFirstTime ? '请设置 6 位以上密码' : '请输入密码'"
                :value="password"
                :disabled="isSubmitting"
                autofocus
                :autocomplete="isFirstTime ? 'new-password' : 'current-password'"
                data-testid="login-password"
                @input="password = ($event.target as HTMLInputElement).value"
              />

              <Input
                v-if="isFirstTime"
                id="passwordConfirm"
                type="password"
                appearance="login"
                allow-toggle-password
                icon-type="password"
                label="确认密码"
                placeholder="再次确认管理员密码"
                :value="passwordConfirm"
                :disabled="isSubmitting"
                autocomplete="new-password"
                @input="passwordConfirm = ($event.target as HTMLInputElement).value"
              />
            </div>

            <div v-if="error" class="animate-[loginErr_0.25s_ease-out] overflow-hidden">
              <SettingsAlert
                :title="isFirstTime ? '配置失败' : '验证未通过'"
                :message="isParsedApiError(error) ? error.message : String(error)"
                variant="error"
                class="!border-[var(--login-error-border)] !bg-[var(--login-error-bg)] !text-[var(--login-error-text)]"
              />
            </div>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              class="group/btn relative h-12 w-full overflow-hidden rounded-xl border-0 bg-gradient-to-r from-[var(--login-brand-button-start)] to-[var(--login-brand-button-end)] font-medium text-[var(--login-button-text)] shadow-lg shadow-[0_18px_36px_hsl(214_100%_8%_/_0.24)] hover:from-[var(--login-brand-button-start-hover)] hover:to-[var(--login-brand-button-end-hover)]"
              :disabled="isSubmitting"
              data-testid="login-submit"
            >
              <div class="relative z-10 flex items-center justify-center gap-2">
                <template v-if="isSubmitting">
                  <Loader2 class="h-4 w-4 animate-spin" />
                  <span>{{ isFirstTime ? '初始化中...' : '正在建立连接...' }}</span>
                </template>
                <template v-else>
                  <span>{{ isFirstTime ? '完成设置并登录' : '授权进入工作台' }}</span>
                </template>
              </div>
              <div
                class="pointer-events-none absolute inset-0 z-0 -translate-x-full bg-gradient-to-r from-transparent via-white/10 to-transparent group-hover/btn:animate-[shimmer_1.5s_infinite]"
              />
            </Button>
          </form>
        </div>
      </div>

      <p
        class="mt-8 animate-[loginFade_0.4s_ease-out_0.6s_both] text-center font-mono text-xs uppercase tracking-wider text-[var(--login-text-muted)]"
      >
        Secure Connection Established via DSA-V3-TLS
      </p>
    </div>
  </div>
</template>

<style scoped>
@keyframes shimmer {
  100% {
    transform: translateX(100%);
  }
}
@keyframes loginFadeUp {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@keyframes loginScale {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
@keyframes loginFade {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
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

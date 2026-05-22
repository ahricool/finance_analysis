<script setup lang="ts">
import { LogOut, User } from 'lucide-vue-next';
import { ref } from 'vue';
import { RouterLink, RouterView } from 'vue-router';
import ConfirmDialog from '@/components/common/ConfirmDialog.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import { useAuth } from '@/composables/useAuth';
import { APP_NAME } from '@/config/app';
import { mainNavItems } from '@/config/mainNav';
import { useAgentChatStore } from '@/stores/agentChatStore';
import { cn } from '@/utils/cn';
import { storeToRefs } from 'pinia';
import { useAuthStore } from '@/stores/authStore';

const authStore = useAuthStore();
const { currentUser } = storeToRefs(authStore);
const { authEnabled, logout } = useAuth();
const completionBadge = useAgentChatStore((s) => s.completionBadge);
const showLogoutConfirm = ref(false);

async function onLogoutConfirm() {
  showLogoutConfirm.value = false;
  await logout();
}
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <header
      class="fixed inset-x-0 top-0 z-50 border-b border-border/70 bg-card/90 shadow-[0_8px_26px_hsl(222_32%_18%/0.08)] backdrop-blur-xl"
    >
      <div class="mx-auto flex h-16 w-full max-w-[1280px] items-center gap-3 px-3 sm:px-4 lg:px-6">
        <RouterLink
          to="/"
          class="flex min-w-max items-center gap-2 rounded-xl px-2 py-1.5 text-foreground transition-colors hover:bg-hover"
          aria-label="回到首页"
        >
          <span class="flex h-9 w-9 items-center justify-center overflow-hidden rounded-xl bg-white shadow-soft-card">
            <img src="/flower.svg" alt="" class="h-8 w-8" />
          </span>
          <span class="hidden font-display text-base leading-none text-black md:block">{{ APP_NAME }}</span>
        </RouterLink>

        <nav
          class="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto overscroll-x-contain px-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          aria-label="主导航"
        >
          <RouterLink
            v-for="item in mainNavItems"
            :key="item.key"
            v-slot="{ href, navigate, isActive, isExactActive }"
            :to="item.to"
            custom
          >
            <a
              :href="href"
              :aria-label="item.label"
              :class="
                cn(
                  'group relative inline-flex h-10 min-w-max items-center justify-center gap-1.5 rounded-xl px-3 text-sm font-medium transition-colors',
                  (item.exact ? isExactActive : isActive)
                    ? 'bg-[var(--nav-active-bg)] text-[hsl(var(--primary))]'
                    : 'text-secondary-text hover:bg-[var(--nav-hover-bg)] hover:text-foreground',
                )
              "
              @click="navigate"
            >
              <component :is="item.icon" class="h-4 w-4 shrink-0" />
              <span>{{ item.label }}</span>
              <span
                v-if="item.exact ? isExactActive : isActive"
                class="absolute inset-x-3 -bottom-[13px] h-0.5 rounded-full bg-[var(--nav-indicator-bg)]"
              />
              <StatusDot
                v-if="item.badge === 'completion' && completionBadge"
                tone="info"
                data-testid="chat-completion-badge"
                class="absolute right-1 top-1 border-2 border-background shadow-[0_0_10px_var(--nav-indicator-shadow)]"
                aria-label="问股有新消息"
              />
            </a>
          </RouterLink>
        </nav>

        <div
          v-if="authEnabled"
          class="flex min-w-max shrink-0 items-center gap-2"
        >
          <div
            v-if="currentUser"
            class="hidden max-w-[200px] items-center gap-2 rounded-xl border border-border/60 bg-card/80 px-2 py-1 text-xs sm:flex"
            title="当前登录用户"
          >
            <span
              class="flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary/15 text-[10px] font-semibold text-primary"
            >
              <img
                v-if="currentUser.avatarUrl"
                :src="currentUser.avatarUrl"
                alt=""
                class="h-full w-full object-cover"
              />
              <User v-else class="h-3.5 w-3.5" />
            </span>
            <span class="min-w-0 truncate text-left leading-tight">
              <span class="block truncate font-medium text-foreground">{{ currentUser.username }}</span>
              <span class="block truncate text-[10px] text-secondary-text">{{ currentUser.role === 'admin' ? '管理员' : '用户' }}</span>
            </span>
          </div>
          <button
            type="button"
            class="inline-flex h-10 min-w-max items-center justify-center gap-1.5 rounded-xl px-3 text-sm font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
            @click="showLogoutConfirm = true"
          >
            <LogOut class="h-4 w-4" />
            <span class="hidden sm:inline">退出</span>
          </button>
        </div>
      </div>
    </header>

    <main class="mx-auto min-h-screen w-full max-w-[1280px] px-3 pb-4 pt-20 sm:px-4 lg:px-6">
      <RouterView />
    </main>

    <ConfirmDialog
      :is-open="showLogoutConfirm"
      title="退出登录"
      message="确认退出当前登录状态吗？退出后需要重新输入密码。"
      confirm-text="确认退出"
      cancel-text="取消"
      :is-danger="true"
      @confirm="onLogoutConfirm"
      @cancel="showLogoutConfirm = false"
    />
  </div>
</template>

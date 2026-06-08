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
const { logout } = useAuth();
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

        <div class="flex min-w-max shrink-0 items-center gap-2">
          <div
            v-if="currentUser"
            class="group relative flex items-center"
            aria-label="当前登录用户"
          >
            <button
              type="button"
              class="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border/70 bg-primary/15 text-primary shadow-sm transition-colors hover:bg-primary/20 focus:outline-none focus:ring-2 focus:ring-primary/35 focus:ring-offset-2 focus:ring-offset-background"
              aria-haspopup="dialog"
              aria-label="查看当前登录用户信息"
            >
              <img
                v-if="currentUser.avatarUrl"
                :src="currentUser.avatarUrl"
                alt=""
                class="h-full w-full object-cover"
              />
              <User
                v-else
                class="h-5 w-5"
              />
            </button>

            <div
              class="invisible absolute right-0 top-full z-50 w-72 pt-2 opacity-0 transition duration-150 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
            >
              <div class="rounded-lg border border-border/70 bg-card p-4 text-sm shadow-[0_18px_50px_hsl(222_32%_18%/0.18)]">
                <div class="truncate text-center text-base font-semibold text-foreground">
                  {{ currentUser.username }}
                </div>
                <div class="mt-4 space-y-2 text-secondary-text">
                  <div class="flex min-w-0 items-start gap-2">
                    <span class="shrink-0 text-foreground">邮箱：</span>
                    <span class="min-w-0 flex-1 break-all">{{ currentUser.email }}</span>
                  </div>
                  <div class="flex min-w-0 items-center gap-2">
                    <span class="shrink-0 text-foreground">角色：</span>
                    <span class="min-w-0 flex-1 truncate">{{ currentUser.role }}</span>
                  </div>
                </div>
                <div class="mt-4 flex justify-center">
                  <button
                    type="button"
                    class="inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary/35"
                    @click="showLogoutConfirm = true"
                  >
                    <LogOut class="h-4 w-4" />
                    <span>退出</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
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

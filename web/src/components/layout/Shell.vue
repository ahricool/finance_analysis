<script setup lang="ts">
import { ChevronRight, ClipboardList, LogOut, User, UserRound } from 'lucide-vue-next';
import { computed, ref } from 'vue';
import { RouterLink, RouterView, useRoute } from 'vue-router';
import ConfirmDialog from '@/components/common/ConfirmDialog.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import TimezoneSwitcher from '@/components/timezone/TimezoneSwitcher.vue';
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
const route = useRoute();

function isNavItemActive(
  item: (typeof mainNavItems)[number],
  isActive: boolean,
  isExactActive: boolean,
): boolean {
  if (item.activePathPrefix) return route.path.startsWith(item.activePathPrefix);
  return item.exact ? isExactActive : isActive;
}

const genderLabel = computed(() => {
  switch (currentUser.value?.extra?.gender) {
    case 'female':
      return '女';
    case 'male':
      return '男';
    default:
      return '未知';
  }
});

const roleLabel = computed(() => {
  switch (currentUser.value?.role) {
    case 'admin':
      return '女王';
    case 'user':
      return '华尔街韭菜';
    default:
      return '未知领域';
  }
});

async function onLogoutConfirm() {
  showLogoutConfirm.value = false;
  await logout();
}
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <header
      class="fixed inset-x-0 top-0 z-50 border-b border-border/70 bg-card/90 shadow-soft-card backdrop-blur-xl"
    >
      <div class="mx-auto flex h-16 w-full max-w-[1280px] items-center gap-3 px-3 sm:px-4 lg:px-6">
        <RouterLink
          to="/"
          class="flex min-w-max items-center gap-2.5 rounded-xl px-2 py-1.5 text-foreground transition-colors hover:bg-hover"
          aria-label="回到首页"
        >
          <span class="flex h-11 w-11 items-center justify-center overflow-hidden rounded-xl bg-white shadow-soft-card">
            <img
              src="/flower.svg"
              alt=""
              class="h-10 w-10"
            />
          </span>
          <span class="hidden font-display text-lg leading-none text-black md:block">{{ APP_NAME }}</span>
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
                  isNavItemActive(item, isActive, isExactActive)
                    ? 'bg-[var(--nav-active-bg)] text-[hsl(var(--primary))]'
                    : 'text-secondary-text hover:bg-[var(--nav-hover-bg)] hover:text-foreground',
                )
              "
              @click="navigate"
            >
              <component
                :is="item.icon"
                class="h-4 w-4 shrink-0"
              />
              <span>{{ item.label }}</span>
              <span
                v-if="isNavItemActive(item, isActive, isExactActive)"
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
              <div class="overflow-hidden rounded-2xl border border-border/70 bg-card p-2 text-sm shadow-soft-card-strong">
                <div class="space-y-1 px-2 py-2 text-secondary-text">
                  <div class="flex min-w-0 items-center justify-between gap-3 rounded-xl px-2 py-2">
                    <span class="shrink-0 text-foreground">性别</span>
                    <span class="min-w-0 flex-1 truncate text-right">{{ genderLabel }}</span>
                  </div>
                  <div class="flex min-w-0 items-center justify-between gap-3 rounded-xl px-2 py-2">
                    <span class="shrink-0 text-foreground">角色</span>
                    <span class="min-w-0 flex-1 truncate text-right">{{ roleLabel }}</span>
                  </div>
                  <div class="flex min-w-0 items-start justify-between gap-3 rounded-xl px-2 py-2">
                    <span class="shrink-0 text-foreground">邮箱</span>
                    <span class="min-w-0 flex-1 break-all text-right">{{ currentUser.email }}</span>
                  </div>
                </div>
                <div class="border-t border-border/70 py-1">
                  <RouterLink
                    to="/profile"
                    class="flex h-11 w-full items-center gap-2 rounded-xl px-4 text-sm font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary/35"
                  >
                    <UserRound class="h-4 w-4" />
                    <span>个人中心</span>
                    <ChevronRight class="ml-auto h-4 w-4 text-muted-text" />
                  </RouterLink>
                  <RouterLink
                    to="/tasks"
                    class="flex h-11 w-full items-center gap-2 rounded-xl px-4 text-sm font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary/35"
                  >
                    <ClipboardList class="h-4 w-4" />
                    <span>任务中心</span>
                    <ChevronRight class="ml-auto h-4 w-4 text-muted-text" />
                  </RouterLink>
                  <button
                    type="button"
                    class="flex h-11 w-full items-center gap-2 rounded-xl px-4 text-sm font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground focus:outline-none focus:ring-2 focus:ring-primary/35"
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

    <TimezoneSwitcher />

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

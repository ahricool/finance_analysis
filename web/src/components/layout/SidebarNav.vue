<script setup lang="ts">
import { BarChart3, BriefcaseBusiness, Home, LogOut, MessageSquareQuote, Settings2, Star, Wallet } from 'lucide-vue-next';
import { ref } from 'vue';
import { RouterLink } from 'vue-router';
import ConfirmDialog from '@/components/common/ConfirmDialog.vue';
import StatusDot from '@/components/common/StatusDot.vue';
import ThemeToggle from '@/components/theme/ThemeToggle.vue';
import { cn } from '@/utils/cn';
import { useAuth } from '@/composables/useAuth';
import { useAgentChatStore } from '@/stores/agentChatStore';

const { collapsed = false } = defineProps<{
  collapsed?: boolean;
}>();

const emit = defineEmits<{
  navigate: [];
}>();

const { authEnabled, logout } = useAuth();
const completionBadge = useAgentChatStore((s) => s.completionBadge);
const showLogoutConfirm = ref(false);

const navItems = [
  { key: 'home', label: '首页', to: '/', icon: Home, exact: true },
  { key: 'chat', label: '问股', to: '/chat', icon: MessageSquareQuote, badge: 'completion' as const },
  { key: 'watch-list', label: '自选股', to: '/watch-list', icon: Star },
  { key: 'stock-list', label: '持仓股', to: '/stock-list', icon: Wallet },
  { key: 'portfolio', label: '投资组合', to: '/portfolio', icon: BriefcaseBusiness },
  { key: 'backtest', label: '回测', to: '/backtest', icon: BarChart3 },
  { key: 'settings', label: '设置', to: '/settings', icon: Settings2 },
];

async function onLogoutConfirm() {
  showLogoutConfirm.value = false;
  emit('navigate');
  await logout();
}
</script>

<template>
  <div class="flex h-full flex-col">
    <div :class="cn('mb-4 flex items-center gap-2 px-1', collapsed ? 'justify-center' : '')">
      <div
        class="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary-gradient text-[hsl(var(--primary-foreground))] shadow-[0_12px_28px_var(--nav-brand-shadow)]"
      >
        <BarChart3 class="h-5 w-5" />
      </div>
      <p v-if="!collapsed" class="min-w-0 truncate text-sm font-semibold text-foreground">DSA</p>
    </div>

    <nav class="flex flex-1 flex-col gap-1.5" aria-label="主导航">
      <RouterLink
        v-for="item in navItems"
        :key="item.key"
        v-slot="{ href, navigate, isActive, isExactActive }"
        :to="item.to"
        custom
      >
        <a
          :href="href"
          class="group relative flex items-center gap-3 border-x-0 border-y text-sm transition-all h-[var(--nav-item-height)]"
          :class="
            cn(
              collapsed ? 'justify-center px-0' : 'px-[var(--nav-item-padding-x)]',
              (item.exact ? isExactActive : isActive)
                ? 'border-[var(--nav-active-border)] bg-[var(--nav-active-bg)] text-[hsl(var(--primary))] font-medium'
                : 'border-transparent text-secondary-text hover:bg-[var(--nav-hover-bg)] hover:text-foreground',
            )
          "
          :aria-label="item.label"
          @click="
            (e) => {
              navigate(e);
              emit('navigate');
            }
          "
        >
          <span
            v-if="item.exact ? isExactActive : isActive"
            class="absolute top-0 bottom-0 left-0 w-[var(--nav-indicator-width)] bg-[var(--nav-indicator-bg)] shadow-[0_0_10px_var(--nav-indicator-shadow)]"
          />
          <component
            :is="item.icon"
            :class="
              cn(
                'ml-1 h-5 w-5 shrink-0',
                (item.exact ? isExactActive : isActive) ? 'text-[var(--nav-icon-active)]' : 'text-current',
              )
            "
          />
          <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
          <StatusDot
            v-if="item.badge === 'completion' && completionBadge"
            tone="info"
            data-testid="chat-completion-badge"
            :class="
              cn(
                'absolute right-3 border-2 border-background shadow-[0_0_10px_var(--nav-indicator-shadow)]',
                collapsed ? 'right-2 top-2' : '',
              )
            "
            aria-label="问股有新消息"
          />
        </a>
      </RouterLink>
    </nav>

    <div class="mt-4 mb-2">
      <ThemeToggle variant="nav" :collapsed="collapsed" />
    </div>

    <button
      v-if="authEnabled"
      type="button"
      :class="
        cn(
          'mt-5 flex h-11 w-full cursor-pointer select-none items-center gap-3 rounded-2xl border border-transparent px-3 text-sm text-secondary-text transition-all hover:border-border/70 hover:bg-hover hover:text-foreground',
          collapsed ? 'justify-center px-2' : '',
        )
      "
      @click="showLogoutConfirm = true"
    >
      <LogOut class="h-5 w-5 shrink-0" />
      <span v-if="!collapsed">退出</span>
    </button>

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

<script setup lang="ts">
import { computed, ref } from 'vue';
import { storeToRefs } from 'pinia';
import { ChevronDown, LogOut, Monitor, Moon, Sun, User, UserRound } from 'lucide-vue-next';
import { RouterLink, RouterView, useRoute } from 'vue-router';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import AppStatusDot from '@/components/app/AppStatusDot.vue';
import TimezoneSwitcher from '@/components/timezone/TimezoneSwitcher.vue';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

import { useAuth } from '@/composables/useAuth';
import { useTheme } from '@/composables/useTheme';
import { APP_NAME } from '@/config/app';
import { mainNavItems, type MainNavItem, type NavDestination } from '@/config/mainNav';
import { useAgentChatStore } from '@/stores/agentChatStore';
import { useAuthStore } from '@/stores/authStore';
import { cn } from '@/utils/cn';

const route = useRoute();
const authStore = useAuthStore();
const { currentUser } = storeToRefs(authStore);
const { logout } = useAuth();
const { theme, setTheme } = useTheme();
const completionBadge = useAgentChatStore((state) => state.completionBadge);
const showLogoutConfirm = ref(false);

function isDestinationActive(item: NavDestination): boolean {
  if (item.exact) return route.path === item.to;
  if (item.activePathPrefix) return route.path.startsWith(item.activePathPrefix);
  return route.path === item.to || route.path.startsWith(`${item.to}/`);
}

function isNavItemActive(item: MainNavItem): boolean {
  return item.children?.some(isDestinationActive) ?? isDestinationActive(item);
}

const initials = computed(() =>
  (currentUser.value?.username || currentUser.value?.email || 'U').slice(0, 1).toUpperCase(),
);

function setThemePreference(value: string | number | bigint) {
  if (value === 'light' || value === 'dark' || value === 'system') {
    setTheme(value);
  }
}

async function onLogoutConfirm() {
  showLogoutConfirm.value = false;
  await logout();
}

</script>

<template>
  <div class="flex min-h-screen flex-col bg-background text-foreground">
    <header class="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div
        class="mx-auto flex h-14 w-full max-w-[1500px] items-center gap-2 px-6"
        data-testid="shell-header-content"
      >
        <RouterLink
          to="/dashboard"
          class="flex min-w-0 items-center gap-2 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="回到动态"
        >
          <span class="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-brand/15">
            <img
              src="/flower.svg"
              alt=""
              class="size-7"
            />
          </span>
          <span class="truncate text-sm font-semibold tracking-tight block">{{ APP_NAME }}</span>
        </RouterLink>

        <nav
          class="ml-4 min-w-0 flex-1 items-center gap-1 flex"
          aria-label="主导航"
          data-testid="desktop-main-nav"
        >
          <template
            v-for="item in mainNavItems"
            :key="item.key"
          >
            <DropdownMenu
              v-if="item.children"
              :modal="false"
            >
              <DropdownMenuTrigger as-child>
                <Button
                  variant="ghost"
                  size="sm"
                  :aria-label="item.label"
                  :aria-current="isNavItemActive(item) ? 'page' : undefined"
                  :class="isNavItemActive(item) && 'bg-muted text-foreground'"
                >
                  <component :is="item.icon" />{{ item.label }}<ChevronDown class="size-3.5 opacity-60" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                align="start"
                class="w-48"
              >
                <DropdownMenuItem
                  v-for="child in item.children"
                  :key="child.key"
                  as-child
                >
                  <RouterLink
                    :to="child.to"
                    :aria-current="isDestinationActive(child) ? 'page' : undefined"
                    :class="isDestinationActive(child) && 'bg-accent'"
                  >
                    <component :is="child.icon" />{{ child.label }}
                  </RouterLink>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              v-else
              as-child
              variant="ghost"
              size="sm"
            >
              <RouterLink
                :to="item.to"
                :aria-label="item.label"
                :aria-current="isNavItemActive(item) ? 'page' : undefined"
                :class="cn('relative', isNavItemActive(item) && 'bg-muted text-foreground')"
              >
                <component :is="item.icon" />{{ item.label }}
                <AppStatusDot
                  v-if="item.badge === 'completion' && completionBadge"
                  tone="info"
                  class="absolute right-1 top-1"
                  aria-label="问股有新消息"
                />
              </RouterLink>
            </Button>
          </template>
        </nav>

        <div class="ml-auto flex items-center gap-1">
          <TimezoneSwitcher />
          <DropdownMenu
            v-if="currentUser"
            :modal="false"
          >
            <DropdownMenuTrigger as-child>
              <Button
                variant="ghost"
                size="icon"
                aria-label="打开用户菜单"
                class="rounded-full"
              >
                <Avatar class="size-8 border">
                  <AvatarImage
                    v-if="currentUser.avatarUrl"
                    :src="currentUser.avatarUrl"
                    alt=""
                  />
                  <AvatarFallback class="bg-brand/15 text-foreground">
                    <User class="size-4" /><span class="sr-only">{{ initials }}</span>
                  </AvatarFallback>
                </Avatar>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              class="w-64"
            >
              <DropdownMenuLabel>
                <p class="truncate">
                  {{ currentUser.username }}
                </p>
                <p class="truncate font-normal text-muted-foreground">
                  {{ currentUser.email }}
                </p>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem as-child>
                <RouterLink to="/profile/info">
                  <UserRound />个人中心
                </RouterLink>
              </DropdownMenuItem>
              <DropdownMenuLabel>主题</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                :model-value="theme"
                aria-label="主题"
                data-testid="theme-preference"
                @update:model-value="setThemePreference"
              >
                <DropdownMenuRadioItem value="system">
                  <Monitor />跟随系统
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="light">
                  <Sun />浅色
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="dark">
                  <Moon />深色
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                @select="showLogoutConfirm = true"
              >
                <LogOut />退出登录
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>

    <main class="mx-auto w-full max-w-[1500px] flex-1 px-6">
      <RouterView />
    </main>

    <AppConfirmDialog
      :open="showLogoutConfirm"
      title="退出登录"
      description="确认退出当前登录状态吗？退出后需要重新输入密码。"
      confirm-text="确认退出"
      destructive
      @confirm="onLogoutConfirm"
      @update:open="showLogoutConfirm = $event"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { LogOut, Menu, Moon, User, UserRound } from 'lucide-vue-next';
import { RouterLink, RouterView, useRoute } from 'vue-router';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import AppStatusDot from '@/components/app/AppStatusDot.vue';
import TimezoneSwitcher from '@/components/timezone/TimezoneSwitcher.vue';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { Separator } from '@/components/ui/separator';
import { useAuth } from '@/composables/useAuth';
import { useTheme } from '@/composables/useTheme';
import { APP_NAME } from '@/config/app';
import { mainNavItems, type MainNavItem } from '@/config/mainNav';
import { useAgentChatStore } from '@/stores/agentChatStore';
import { useAuthStore } from '@/stores/authStore';
import { cn } from '@/utils/cn';

const route = useRoute();
const authStore = useAuthStore();
const { currentUser } = storeToRefs(authStore);
const { logout } = useAuth();
const { resolvedTheme, setTheme } = useTheme();
const completionBadge = useAgentChatStore((state) => state.completionBadge);
const showLogoutConfirm = ref(false);
const mobileNavOpen = ref(false);

function isNavItemActive(item: MainNavItem): boolean {
  if (item.activePaths)
    return item.activePaths.some(
      (path) => route.path === path || route.path.startsWith(`${path}/`),
    );
  if (item.activePathPrefix) return route.path.startsWith(item.activePathPrefix);
  if (item.exact) return route.path === item.to;
  return route.path === item.to || route.path.startsWith(`${item.to}/`);
}

const initials = computed(() =>
  (currentUser.value?.username || currentUser.value?.email || 'U').slice(0, 1).toUpperCase(),
);

function toggleTheme(checked: boolean) {
  setTheme(checked ? 'dark' : 'light');
}
async function onLogoutConfirm() {
  showLogoutConfirm.value = false;
  await logout();
}
watch(
  () => route.fullPath,
  () => {
    mobileNavOpen.value = false;
  },
);
</script>

<template>
  <div class="flex min-h-dvh flex-col bg-background text-foreground">
    <header
      class="sticky top-0 z-40 border-b bg-background/95 pt-[env(safe-area-inset-top)] backdrop-blur"
    >
      <div class="safe-inline mx-auto flex h-14 w-full max-w-7xl items-center gap-2">
        <Sheet v-model:open="mobileNavOpen">
          <SheetTrigger as-child>
            <Button
              variant="ghost"
              size="icon"
              class="md:hidden"
              aria-label="打开主导航"
              data-testid="mobile-nav-trigger"
            >
              <Menu class="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent
            side="left"
            class="w-72 gap-0 p-0"
          >
            <SheetHeader class="border-b px-4 py-4 text-left">
              <SheetTitle class="flex items-center gap-2">
                <span
                  class="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-brand/15"
                ><img
                  src="/flower.svg"
                  alt=""
                  class="size-7"
                /></span>
                {{ APP_NAME }}
              </SheetTitle>
              <SheetDescription class="sr-only">
                主导航
              </SheetDescription>
            </SheetHeader>
            <nav
              class="grid gap-1 p-3"
              aria-label="主导航"
              data-testid="mobile-main-nav"
            >
              <Button
                v-for="item in mainNavItems"
                :key="item.key"
                as-child
                variant="ghost"
                class="h-10 justify-start"
              >
                <RouterLink
                  :to="item.to"
                  :aria-label="item.label"
                  :aria-current="isNavItemActive(item) ? 'page' : undefined"
                  :class="
                    cn(
                      'relative',
                      isNavItemActive(item)
                        ? 'bg-muted text-foreground'
                        : 'text-muted-foreground',
                    )
                  "
                >
                  <component
                    :is="item.icon"
                    class="size-4"
                  /><span>{{ item.label }}</span>
                  <AppStatusDot
                    v-if="item.badge === 'completion' && completionBadge"
                    tone="info"
                    aria-label="问股有新消息"
                  />
                </RouterLink>
              </Button>
              <Separator class="my-2" />
              <Button
                as-child
                variant="ghost"
                class="h-10 justify-start"
              >
                <RouterLink
                  to="/profile/info"
                  :class="route.path.startsWith('/profile') ? 'bg-muted text-foreground' : 'text-muted-foreground'"
                >
                  <UserRound class="size-4" />个人中心
                </RouterLink>
              </Button>
            </nav>
          </SheetContent>
        </Sheet>

        <RouterLink
          to="/analysis"
          class="flex min-w-0 items-center gap-2 rounded-md p-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="回到首页"
        >
          <span
            class="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-brand/15"
          ><img
            src="/flower.svg"
            alt=""
            class="size-7"
          /></span>
          <span class="truncate text-sm font-semibold tracking-tight max-md:hidden lg:text-base">{{
            APP_NAME
          }}</span>
        </RouterLink>

        <nav
          class="ml-4 hidden min-w-0 flex-1 items-center gap-1 md:flex"
          aria-label="主导航"
          data-testid="desktop-main-nav"
        >
          <Button
            v-for="item in mainNavItems"
            :key="item.key"
            as-child
            variant="ghost"
            size="sm"
          >
            <RouterLink
              :to="item.to"
              :aria-label="item.label"
              :aria-current="isNavItemActive(item) ? 'page' : undefined"
              :class="
                cn(
                  'relative gap-2 px-2.5 lg:px-3',
                  isNavItemActive(item)
                    ? 'bg-muted text-foreground'
                    : 'text-muted-foreground hover:text-foreground',
                )
              "
            >
              <span>{{ item.label }}</span>
              <AppStatusDot
                v-if="item.badge === 'completion' && completionBadge"
                tone="info"
                class="absolute -right-0.5 -top-0.5 size-2 border border-background"
                aria-label="问股有新消息"
              />
            </RouterLink>
          </Button>
        </nav>

        <div class="ml-auto flex items-center gap-1">
          <TimezoneSwitcher />
          <DropdownMenu v-if="currentUser">
            <DropdownMenuTrigger
              aria-label="打开用户菜单"
              class="rounded-full outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <Avatar class="size-8 border">
                <AvatarImage
                  v-if="currentUser.avatarUrl"
                  :src="currentUser.avatarUrl"
                  alt=""
                /><AvatarFallback class="bg-muted text-muted-foreground">
                  <User class="size-4" /><span class="sr-only">{{ initials }}</span>
                </AvatarFallback>
              </Avatar>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              class="w-64"
            >
              <DropdownMenuLabel>
                <p class="truncate">
                  {{ currentUser.username }}
                </p>
                <p class="truncate text-xs font-normal text-muted-foreground">
                  {{ currentUser.email }}
                </p>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem as-child>
                <RouterLink
                  to="/profile/info"
                  class="cursor-pointer"
                >
                  <UserRound />个人中心
                </RouterLink>
              </DropdownMenuItem>
              <DropdownMenuCheckboxItem
                class="cursor-pointer"
                :model-value="resolvedTheme === 'dark'"
                @update:model-value="toggleTheme"
              >
                <Moon />深色模式
              </DropdownMenuCheckboxItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                class="text-destructive focus:text-destructive"
                @select="showLogoutConfirm = true"
              >
                <LogOut />退出登录
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>

    <main
      class="safe-inline mx-auto w-full max-w-7xl flex-1 pb-[env(safe-area-inset-bottom)]"
    >
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

<style scoped>
.safe-inline {
  padding-left: max(1rem, env(safe-area-inset-left));
  padding-right: max(1rem, env(safe-area-inset-right));
}
@media (min-width: 1024px) {
  .safe-inline {
    padding-left: max(1.5rem, env(safe-area-inset-left));
    padding-right: max(1.5rem, env(safe-area-inset-right));
  }
}
</style>

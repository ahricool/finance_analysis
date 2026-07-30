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
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import { ScrollArea } from '@/components/ui/scroll-area';
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
const mobileMoreOpen = ref(false);

const mobilePrimaryKeys = new Set(['analysis', 'calendar', 'market', 'chat']);
const mobilePrimaryItems = computed(() =>
  mainNavItems.filter((item) => mobilePrimaryKeys.has(item.key)),
);
const mobileMoreItems = computed(() =>
  mainNavItems.filter((item) => !mobilePrimaryKeys.has(item.key)),
);

function isNavItemActive(item: MainNavItem): boolean {
  if (item.activePaths)
    return item.activePaths.some(
      (path) => route.path === path || route.path.startsWith(`${path}/`),
    );
  if (item.activePathPrefix) return route.path.startsWith(item.activePathPrefix);
  if (item.exact) return route.path === item.to;
  return route.path === item.to || route.path.startsWith(`${item.to}/`);
}

const moreActive = computed(
  () =>
    mobileMoreItems.value.some((item) => isNavItemActive(item)) ||
    route.path.startsWith('/profile'),
);
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
    mobileMoreOpen.value = false;
  },
);
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <header
      class="fixed inset-x-0 top-0 z-40 border-b bg-background/92 pt-[env(safe-area-inset-top)] backdrop-blur-xl md:pt-0"
    >
      <div class="safe-inline mx-auto flex h-16 w-full max-w-7xl items-center gap-3">
        <RouterLink
          to="/analysis"
          class="flex min-w-0 items-center gap-2 rounded-lg p-1.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="回到分析"
        >
          <span
            class="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-primary/10"
          ><img
            src="/flower.svg"
            alt=""
            class="size-8"
          /></span>
          <span class="hidden truncate text-sm font-semibold tracking-tight lg:block">{{
            APP_NAME
          }}</span>
        </RouterLink>

        <nav
          class="hidden min-w-0 flex-1 items-center justify-center gap-1 md:flex"
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
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
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
                class="absolute right-1 top-1 border border-background"
                aria-label="问股有新消息"
              />
            </RouterLink>
          </Button>
        </nav>

        <DropdownMenu v-if="currentUser">
          <DropdownMenuTrigger
            aria-label="打开用户菜单"
            class="ml-auto rounded-full outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <Avatar class="size-10 border">
              <AvatarImage
                v-if="currentUser.avatarUrl"
                :src="currentUser.avatarUrl"
                alt=""
              /><AvatarFallback class="bg-primary/10 text-primary">
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
    </header>

    <main
      class="safe-inline mx-auto min-h-screen w-full max-w-7xl pb-[calc(5.5rem+env(safe-area-inset-bottom))] pt-[calc(4rem+env(safe-area-inset-top))] md:pb-8 md:pt-20"
    >
      <RouterView />
    </main>

    <nav
      class="fixed inset-x-0 bottom-0 z-40 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl md:hidden"
      aria-label="主导航"
      data-testid="mobile-main-nav"
    >
      <div
        class="mx-auto grid h-16 max-w-lg grid-cols-5 px-[max(.25rem,env(safe-area-inset-left))] pr-[max(.25rem,env(safe-area-inset-right))]"
      >
        <Button
          v-for="item in mobilePrimaryItems"
          :key="item.key"
          as-child
          variant="ghost"
          class="m-1 h-auto min-h-12 min-w-0 p-0"
        >
          <RouterLink
            :to="item.to"
            :aria-label="item.label"
            :aria-current="isNavItemActive(item) ? 'page' : undefined"
            :class="
              cn(
                'relative flex size-full min-w-0 flex-col items-center justify-center gap-0.5 rounded-lg text-[11px] font-medium',
                isNavItemActive(item) ? 'bg-primary/10 text-primary' : 'text-muted-foreground',
              )
            "
          >
            <component
              :is="item.icon"
              class="size-5"
            /><span class="truncate">{{
              item.label
            }}</span><AppStatusDot
              v-if="item.badge === 'completion' && completionBadge"
              tone="info"
              class="absolute right-[calc(50%-1rem)] top-1"
            />
          </RouterLink>
        </Button>
        <Button
          variant="ghost"
          aria-label="更多"
          :aria-current="moreActive ? 'page' : undefined"
          :class="
            cn(
              'm-1 h-auto min-h-12 min-w-0 flex-col gap-0.5 rounded-lg p-0 text-[11px] font-medium',
              moreActive ? 'bg-primary/10 text-primary' : 'text-muted-foreground',
            )
          "
          @click="mobileMoreOpen = true"
        >
          <Menu class="size-5" /><span>更多</span>
        </Button>
      </div>
    </nav>

    <Sheet v-model:open="mobileMoreOpen">
      <SheetContent
        side="bottom"
        class="max-h-[85dvh] rounded-t-2xl pb-[max(1rem,env(safe-area-inset-bottom))]"
      >
        <SheetHeader class="text-left">
          <SheetTitle>更多功能</SheetTitle><SheetDescription>回测、量化、任务与账号设置</SheetDescription>
        </SheetHeader>
        <Separator />
        <ScrollArea class="min-h-0 flex-1">
          <nav
            class="grid gap-2 pr-3"
            aria-label="更多功能"
          >
            <Button
              v-for="item in mobileMoreItems"
              :key="item.key"
              as-child
              variant="outline"
              class="h-12 justify-start"
            >
              <RouterLink
                :to="item.to"
                :aria-current="isNavItemActive(item) ? 'page' : undefined"
                :class="isNavItemActive(item) ? 'border-primary/30 bg-primary/10 text-primary' : ''"
              >
                <component
                  :is="item.icon"
                  class="size-5"
                />{{ item.label }}
              </RouterLink>
            </Button>
            <Button
              as-child
              variant="outline"
              class="h-12 justify-start"
            >
              <RouterLink to="/profile/info">
                <UserRound class="size-5" />个人中心
              </RouterLink>
            </Button>
          </nav>
        </ScrollArea>
        <SheetFooter class="text-xs text-muted-foreground">
          必要操作均可通过触控完成
        </SheetFooter>
      </SheetContent>
    </Sheet>

    <TimezoneSwitcher />
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
  padding-left: max(0.75rem, env(safe-area-inset-left));
  padding-right: max(0.75rem, env(safe-area-inset-right));
}
@media (min-width: 640px) {
  .safe-inline {
    padding-left: max(1rem, env(safe-area-inset-left));
    padding-right: max(1rem, env(safe-area-inset-right));
  }
}
@media (min-width: 1024px) {
  .safe-inline {
    padding-left: max(1.5rem, env(safe-area-inset-left));
    padding-right: max(1.5rem, env(safe-area-inset-right));
  }
}
</style>

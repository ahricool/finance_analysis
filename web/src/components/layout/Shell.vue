<script setup lang="ts">
import { Menu } from 'lucide-vue-next';
import { onMounted, onUnmounted, ref } from 'vue';
import { RouterView } from 'vue-router';
import Drawer from '@/components/common/Drawer.vue';
import SidebarNav from '@/components/layout/SidebarNav.vue';
import ThemeToggle from '@/components/theme/ThemeToggle.vue';
import { cn } from '@/utils/cn';

const mobileOpen = ref(false);
const collapsed = false;

function onResize() {
  if (window.innerWidth >= 1024) {
    mobileOpen.value = false;
  }
}

onMounted(() => {
  window.addEventListener('resize', onResize);
});

onUnmounted(() => {
  window.removeEventListener('resize', onResize);
});
</script>

<template>
  <div class="min-h-screen bg-background text-foreground">
    <div class="pointer-events-none fixed inset-x-0 top-3 z-40 flex items-start justify-between px-3 lg:hidden">
      <button
        type="button"
        class="pointer-events-auto inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-card/85 text-secondary-text shadow-soft-card backdrop-blur-md transition-colors hover:bg-hover hover:text-foreground"
        aria-label="打开导航菜单"
        @click="mobileOpen = true"
      >
        <Menu class="h-5 w-5" />
      </button>
      <div class="pointer-events-auto">
        <ThemeToggle />
      </div>
    </div>

    <div class="mx-auto flex min-h-screen w-full max-w-[1680px] px-3 py-3 sm:px-4 sm:py-4 lg:px-5">
      <aside
        :class="
          cn(
            'sticky top-3 z-40 hidden shrink-0 overflow-visible rounded-[1.5rem] border border-[var(--shell-sidebar-border)] bg-card/72 p-2 shadow-soft-card backdrop-blur-sm transition-[width] duration-200 lg:flex',
            'max-h-[calc(100vh-1.5rem)] self-start sm:top-4 sm:max-h-[calc(100vh-2rem)]',
            collapsed ? 'w-[64px]' : 'w-[116px]',
          )
        "
        aria-label="桌面侧边导航"
      >
        <SidebarNav :collapsed="collapsed" @navigate="mobileOpen = false" />
      </aside>

      <main class="min-h-0 min-w-0 flex-1 touch-pan-y pt-14 lg:pl-3 lg:pt-0">
        <RouterView />
      </main>
    </div>

    <Drawer
      :is-open="mobileOpen"
      title="导航菜单"
      width="max-w-xs"
      :z-index="90"
      side="left"
      @close="mobileOpen = false"
    >
      <SidebarNav @navigate="mobileOpen = false" />
    </Drawer>
  </div>
</template>

<script setup lang="ts">
import { Menu, PanelLeftClose, PanelLeftOpen } from 'lucide-vue-next';
import { computed } from 'vue';
import { useRoute } from 'vue-router';
import { APP_NAME } from '@/config/app';

defineProps<{
  collapsed: boolean;
}>();

const emit = defineEmits<{
  toggleSidebar: [];
  openMobileNav: [];
}>();

const route = useRoute();

const TITLES: Record<string, { title: string; description: string }> = {
  '/': { title: '首页', description: '股票分析与历史报告工作台' },
  '/chat': { title: '问股', description: '多轮策略问答与历史会话管理' },
  '/backtest': { title: '回测', description: '回测任务与结果浏览' },
};

const current = computed(
  () => TITLES[route.path] ?? { title: APP_NAME, description: 'Web workspace' },
);
</script>

<template>
  <header class="sticky top-0 z-30 border-b border-border/70 bg-background/86 backdrop-blur-xl">
    <div class="mx-auto flex h-16 w-full max-w-[1280px] items-center gap-3 px-4 sm:px-6 lg:px-8">
      <button
        type="button"
        class="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border/80 bg-card/86 text-secondary-text shadow-soft-card transition-all hover:-translate-y-0.5 hover:bg-hover hover:text-foreground lg:hidden"
        aria-label="打开导航菜单"
        @click="emit('openMobileNav')"
      >
        <Menu class="h-5 w-5" />
      </button>

      <button
        type="button"
        class="hidden h-10 w-10 items-center justify-center rounded-xl border border-border/80 bg-card/86 text-secondary-text shadow-soft-card transition-all hover:-translate-y-0.5 hover:bg-hover hover:text-foreground lg:inline-flex"
        :aria-label="collapsed ? '展开侧边栏' : '折叠侧边栏'"
        @click="emit('toggleSidebar')"
      >
        <PanelLeftOpen v-if="collapsed" class="h-5 w-5" />
        <PanelLeftClose v-else class="h-5 w-5" />
      </button>

      <div class="min-w-0 flex-1">
        <p class="truncate font-display text-xl leading-tight text-foreground">{{ current.title }}</p>
        <p class="truncate text-xs text-secondary-text">{{ current.description }}</p>
      </div>
    </div>
  </header>
</template>

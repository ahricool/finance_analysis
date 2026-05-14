<script setup lang="ts">
import ThemeToggle from '@/components/theme/ThemeToggle.vue';
import { Menu, PanelLeftClose, PanelLeftOpen } from 'lucide-vue-next';
import { computed } from 'vue';
import { useRoute } from 'vue-router';

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
  '/settings': { title: '设置', description: '系统配置、模型与认证管理' },
};

const current = computed(
  () => TITLES[route.path] ?? { title: 'Daily Stock Analysis', description: 'Web workspace' },
);
</script>

<template>
  <header class="sticky top-0 z-30 border-b border-border/60 bg-background/84 backdrop-blur-xl">
    <div class="mx-auto flex h-16 w-full max-w-[1680px] items-center gap-3 px-4 sm:px-6 lg:px-8">
      <button
        type="button"
        class="inline-flex h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-card/70 text-secondary-text transition-colors hover:bg-hover hover:text-foreground lg:hidden"
        aria-label="打开导航菜单"
        @click="emit('openMobileNav')"
      >
        <Menu class="h-5 w-5" />
      </button>

      <button
        type="button"
        class="hidden h-10 w-10 items-center justify-center rounded-xl border border-border/70 bg-card/70 text-secondary-text transition-colors hover:bg-hover hover:text-foreground lg:inline-flex"
        :aria-label="collapsed ? '展开侧边栏' : '折叠侧边栏'"
        @click="emit('toggleSidebar')"
      >
        <PanelLeftOpen v-if="collapsed" class="h-5 w-5" />
        <PanelLeftClose v-else class="h-5 w-5" />
      </button>

      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-semibold text-foreground">{{ current.title }}</p>
        <p class="truncate text-xs text-secondary-text">{{ current.description }}</p>
      </div>

      <ThemeToggle />
    </div>
  </header>
</template>

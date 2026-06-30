import type { Component } from 'vue';
import {
  CalendarDays,
  ChartNoAxesCombined,
  Home,
  MessageSquareQuote,
} from 'lucide-vue-next';

/** 主导航项（Shell 顶部栏等单一数据源） */
export type MainNavItem = {
  key: string;
  label: string;
  to: string;
  icon: Component;
  exact?: boolean;
  activePathPrefix?: string;
  badge?: 'completion';
};

export const mainNavItems: MainNavItem[] = [
  { key: 'home', label: '首页', to: '/', icon: Home, exact: true },
  { key: 'calendar', label: '日历', to: '/calendar', icon: CalendarDays },
  {
    key: 'market',
    label: '市场',
    to: '/market/watch-list',
    icon: ChartNoAxesCombined,
    activePathPrefix: '/market/',
  },
  { key: 'chat', label: '问股', to: '/chat', icon: MessageSquareQuote, badge: 'completion' },
];

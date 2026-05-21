import type { Component } from 'vue';
import {
  BarChart3,
  BriefcaseBusiness,
  CalendarDays,
  Home,
  MessageSquareQuote,
  Star,
  Wallet,
} from 'lucide-vue-next';

/** 主导航项（Shell 顶部栏等单一数据源） */
export type MainNavItem = {
  key: string;
  label: string;
  to: string;
  icon: Component;
  exact?: boolean;
  badge?: 'completion';
};

export const mainNavItems: MainNavItem[] = [
  { key: 'home', label: '首页', to: '/', icon: Home, exact: true },
  { key: 'calendar', label: '日历', to: '/calendar', icon: CalendarDays },
  { key: 'watch-list', label: '自选股', to: '/watch-list', icon: Star },
  { key: 'stock-list', label: '持仓股', to: '/stock-list', icon: Wallet },
  { key: 'chat', label: '问股', to: '/chat', icon: MessageSquareQuote, badge: 'completion' },
  { key: 'portfolio', label: '投资组合', to: '/portfolio', icon: BriefcaseBusiness },
  { key: 'backtest', label: '回测', to: '/backtest', icon: BarChart3 },
];

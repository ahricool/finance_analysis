import type { Component } from 'vue';
import {
  BrainCircuit,
  CalendarDays,
  ChartNoAxesCombined,
  FlaskConical,
  MessageSquareQuote,
  Sigma,
} from 'lucide-vue-next';

/** 主导航项（Shell 顶部栏等单一数据源） */
export type MainNavItem = {
  key: string;
  label: string;
  to: string;
  icon: Component;
  exact?: boolean;
  activePathPrefix?: string;
  activePaths?: string[];
  badge?: 'completion';
};

export const mainNavItems: MainNavItem[] = [
  { key: 'analysis', label: '分析', to: '/analysis', icon: BrainCircuit, exact: true },
  { key: 'calendar', label: '日历', to: '/calendar', icon: CalendarDays },
  {
    key: 'market',
    label: '市场',
    to: '/market/watch-list',
    icon: ChartNoAxesCombined,
    activePaths: ['/market/watch-list', '/market/holdings', '/market/signals'],
  },
  { key: 'backtest', label: '回测', to: '/market/backtests', icon: FlaskConical, activePathPrefix: '/market/backtests' },
  { key: 'quant', label: '量化', to: '/market/quant', icon: Sigma, activePathPrefix: '/market/quant' },
  { key: 'chat', label: '问股', to: '/chat', icon: MessageSquareQuote, badge: 'completion' },
];

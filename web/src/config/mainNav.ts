import type { Component } from 'vue';
import {
  Activity,
  BarChart3,
  BrainCircuit,
  CalendarDays,
  ChartNoAxesCombined,
  ClipboardList,
  MessageSquareQuote,
  Sigma,
  Star,
  Wallet,
} from 'lucide-vue-next';

export type NavDestination = {
  key: string;
  label: string;
  to: string;
  icon: Component;
  activePathPrefix?: string;
  exact?: boolean;
  badge?: 'completion';
};

export type MainNavItem = NavDestination & {
  children?: NavDestination[];
};

export const mainNavItems: MainNavItem[] = [
  {
    key: 'analysis',
    label: '分析',
    to: '/analysis',
    icon: BrainCircuit,
    exact: true,
  },
  {
    key: 'market',
    label: '市场',
    to: '/market/watch-list',
    icon: ChartNoAxesCombined,
    activePathPrefix: '/market/',
    children: [
      { key: 'watch-list', label: '自选股', to: '/market/watch-list', icon: Star },
      { key: 'holdings', label: '投资组合', to: '/market/holdings', icon: Wallet },
      { key: 'signals', label: '信号评估', to: '/market/signals', icon: Activity },
    ],
  },
  {
    key: 'research',
    label: '研究',
    to: '/market/quant',
    icon: BarChart3,
    children: [
      {
        key: 'quant',
        label: '量化研究',
        to: '/market/quant',
        icon: Sigma,
        activePathPrefix: '/market/quant',
      },
    ],
  },
  { key: 'calendar', label: '日历', to: '/calendar', icon: CalendarDays },
  {
    key: 'chat',
    label: '问股',
    to: '/chat',
    icon: MessageSquareQuote,
    badge: 'completion',
  },
  { key: 'tasks', label: '任务', to: '/tasks', icon: ClipboardList },
];

export const allNavDestinations = mainNavItems.flatMap((item) => item.children ?? [item]);

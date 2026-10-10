import type { Component } from 'vue';
import {
  Banknote,
  Bitcoin,
  Building2,
  CalendarDays,
  ChartCandlestick,
  ChartNoAxesCombined,
  ClipboardList,
  ClipboardCheck,
  ListChecks,
  Combine,
  Crosshair,
  Flame,
  Globe2,
  LayoutDashboard,
  RefreshCcw,
  Sigma,
  Star,
  Target,
  TrendingUp,
  Wallet,
} from 'lucide-vue-next';

export type NavDestination = {
  key: string;
  label: string;
  to: string;
  icon: Component;
  activePathPrefix?: string;
  exact?: boolean;
  adminOnly?: boolean;
};

export type MainNavItem = NavDestination & {
  children?: NavDestination[];
};

export const marketNavItems: NavDestination[] = [
  { key: 'watch-list', label: '自选股', to: '/market/watch-list', icon: Star },
  { key: 'holdings', label: '投资组合', to: '/market/holdings', icon: Wallet },
];

export const researchNavItems: NavDestination[] = [
  { key: 'options-intelligence', label: '期权情报', to: '/research/options-intelligence', icon: ChartNoAxesCombined },
  { key: 'intraday-confirmation', label: '盘中确认', to: '/research/intraday-confirmation', icon: Crosshair },
  { key: 'signal-center', label: '信号中心', to: '/research/signal-center', icon: Target },
  { key: 'confluence', label: '多信号共振', to: '/research/confluence', icon: Combine },
  {
    key: 'etf-rotation',
    label: 'ETF 动量轮动',
    to: '/research/etf-rotation',
    icon: RefreshCcw,
  },
  {
    key: 'trend-following',
    label: '趋势跟踪',
    to: '/research/trend-following',
    icon: TrendingUp,
  },
  { key: 'industry-strength', label: '行业强度', to: '/research/industry-strength', icon: Building2 },
  { key: 'dragon-tiger-flow', label: '龙虎榜资金流向', to: '/research/dragon-tiger-flow', icon: Banknote },
  { key: 'market-sentiment', label: '市场情绪', to: '/research/market-sentiment', icon: Flame },
  { key: 'macro', label: '宏观数据', to: '/research/macro', icon: Globe2 },
  {
    key: 'quant',
    label: '量化研究',
    to: '/research/quant',
    icon: Sigma,
    activePathPrefix: '/research/quant',
  },
];

export const cryptoNavItems: NavDestination[] = [
  { key: 'crypto-btc', label: 'BTC 交易', to: '/crypto/btc', icon: Bitcoin },
];

export const taskNavItems: NavDestination[] = [
  { key: 'scheduled', label: '定时任务', to: '/tasks/scheduled', icon: ClipboardCheck, adminOnly: true },
  { key: 'runs', label: '执行记录', to: '/tasks/runs', icon: ListChecks },
];

export const mainNavItems: MainNavItem[] = [
  { key: 'dashboard', label: '市场动态', to: '/dashboard', icon: LayoutDashboard, exact: true },
  {
    key: 'market',
    label: '市场',
    to: '/market/watch-list',
    icon: ChartCandlestick,
    activePathPrefix: '/market/',
    children: marketNavItems,
  },
  { key: 'timeline', label: '时间线', to: '/timeline', icon: CalendarDays },
  {
    key: 'research',
    label: '研究',
    to: '/research/etf-rotation',
    icon: ChartNoAxesCombined,
    activePathPrefix: '/research/',
    children: researchNavItems,
  },
  {
    key: 'crypto',
    label: '加密货币',
    to: '/crypto/btc',
    icon: Bitcoin,
    activePathPrefix: '/crypto/',
    children: cryptoNavItems,
  },
  { key: 'tasks', label: '任务中心', to: '/tasks', icon: ClipboardList, children: taskNavItems },
];

export const allNavDestinations = mainNavItems.flatMap((item) => item.children ?? [item]);

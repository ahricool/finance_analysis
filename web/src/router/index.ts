import { createRouter, createWebHistory, type RouteLocationNormalizedLoaded } from 'vue-router';
import Shell from '@/components/layout/Shell.vue';
import { formatDocumentTitle } from '@/config/app';
import { useAuthStore } from '@/stores/authStore';

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean;
    title?: string;
  }
}

const HomePage = () => import('@/pages/HomePage.vue');
const ChatPage = () => import('@/pages/ChatPage.vue');
const MarketPage = () => import('@/pages/MarketPage.vue');
const MarketWatchListPage = () => import('@/pages/WatchListPage.vue');
const MarketHoldingsPage = () => import('@/pages/StockListPage.vue');
const SignalEvaluationPage = () => import('@/pages/market/SignalEvaluationPage.vue');
const BacktestPage = () => import('@/pages/market/BacktestPage.vue');
const BacktestDetailPage = () => import('@/pages/market/BacktestDetailPage.vue');
const QuantDashboardPage = () => import('@/pages/market/quant/QuantDashboardPage.vue');
const QuantSignalsPage = () => import('@/pages/market/quant/QuantSignalsPage.vue');
const QuantSignalDetailPage = () => import('@/pages/market/quant/QuantSignalDetailPage.vue');
const QuantModelsPage = () => import('@/pages/market/quant/QuantModelsPage.vue');
const QuantModelRunPage = () => import('@/pages/market/quant/QuantModelRunPage.vue');
const QuantEventsPage = () => import('@/pages/market/quant/QuantEventsPage.vue');
const QuantPortfoliosPage = () => import('@/pages/market/quant/QuantPortfoliosPage.vue');
const LoginPage = () => import('@/pages/LoginPage.vue');
const CalendarPage = () => import('@/pages/CalendarPage.vue');
const ProfilePage = () => import('@/pages/ProfilePage.vue');
const TasksPage = () => import('@/pages/TasksPage.vue');
const NotFoundPage = () => import('@/pages/NotFoundPage.vue');

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: Shell,
      children: [
        { path: '', name: 'home', component: HomePage },
        { path: 'chat', name: 'chat', component: ChatPage, meta: { title: '问股' } },
        {
          path: 'market',
          component: MarketPage,
          meta: { title: '市场' },
          children: [
            {
              path: 'watch-list',
              name: 'market-watch-list',
              component: MarketWatchListPage,
              meta: { title: '自选股' },
            },
            {
              path: 'holdings',
              name: 'market-holdings',
              component: MarketHoldingsPage,
              meta: { title: '持仓股' },
            },
            {
              path: 'signals',
              name: 'market-signals',
              component: SignalEvaluationPage,
              meta: { title: '信号评估' },
            },
            {
              path: 'backtests',
              name: 'market-backtests',
              component: BacktestPage,
              meta: { title: '策略回测' },
            },
            {
              path: 'backtests/:runId',
              name: 'market-backtest-detail',
              component: BacktestDetailPage,
              meta: { title: '回测详情' },
            },
            { path: 'quant', name: 'market-quant', component: QuantDashboardPage, meta: { title: '量化研究' } },
            { path: 'quant/signals', name: 'market-quant-signals', component: QuantSignalsPage, meta: { title: '模型选股' } },
            { path: 'quant/signals/:code', name: 'market-quant-signal-detail', component: QuantSignalDetailPage, meta: { title: '选股详情' } },
            { path: 'quant/models', name: 'market-quant-models', component: QuantModelsPage, meta: { title: '量化模型' } },
            { path: 'quant/models/:runId', name: 'market-quant-model-run', component: QuantModelRunPage, meta: { title: '模型运行详情' } },
            { path: 'quant/events', name: 'market-quant-events', component: QuantEventsPage, meta: { title: '市场事件' } },
            { path: 'quant/portfolios', name: 'market-quant-portfolios', component: QuantPortfoliosPage, meta: { title: '组合建议' } },
          ],
        },
        { path: 'calendar', name: 'calendar', component: CalendarPage, meta: { title: '日历记录' } },
        { path: 'profile', name: 'profile', component: ProfilePage, meta: { title: '个人中心' } },
        { path: 'tasks', name: 'tasks', component: TasksPage, meta: { title: '任务中心' } },
        { path: 'tasks/scheduled', name: 'tasks-scheduled', component: TasksPage, meta: { title: '任务中心' } },
        { path: 'tasks/runs', name: 'tasks-runs', component: TasksPage, meta: { title: '任务中心' } },
        { path: ':pathMatch(.*)*', name: 'not-found', component: NotFoundPage, meta: { title: '页面未找到' } },
      ],
    },
    { path: '/login', name: 'login', component: LoginPage, meta: { public: true, title: '登录' } },
  ],
});

export function resolveDocumentTitle(to: Pick<RouteLocationNormalizedLoaded, 'matched'>): string {
  const pageTitle = [...to.matched].reverse().find((record) => typeof record.meta.title === 'string')?.meta.title;
  return formatDocumentTitle(pageTitle);
}

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (auth.isLoading) {
    await auth.fetchStatus();
  }

  const isPublic = to.meta.public === true;
  if (!auth.loggedIn && !isPublic) {
    return {
      path: '/login',
      query: { redirect: to.fullPath },
      replace: true,
    };
  }

  if (to.path === '/login' && auth.loggedIn) {
    return { path: '/', replace: true };
  }

  return true;
});

router.afterEach((to) => {
  document.title = resolveDocumentTitle(to);
});

export default router;

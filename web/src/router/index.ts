import { createRouter, createWebHistory, type RouteLocationGeneric, type RouteLocationNormalizedLoaded } from 'vue-router';
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
const MarketPage = () => import('@/pages/MarketPage.vue');
const ResearchPage = () => import('@/pages/ResearchPage.vue');
const MarketWatchListPage = () => import('@/pages/WatchListPage.vue');
const MarketHoldingsPage = () => import('@/pages/StockListPage.vue');
const QuantPage = () => import('@/pages/market/QuantPage.vue');
const QuantDashboardPage = () => import('@/pages/market/quant/QuantDashboardPage.vue');
const QuantSignalsPage = () => import('@/pages/market/quant/QuantSignalsPage.vue');
const QuantSignalDetailPage = () => import('@/pages/market/quant/QuantSignalDetailPage.vue');
const QuantDatasetsPage = () => import('@/pages/market/quant/QuantDatasetsPage.vue');
const QuantModelsPage = () => import('@/pages/market/quant/QuantModelsPage.vue');
const QuantModelRunPage = () => import('@/pages/market/quant/QuantModelRunPage.vue');
const QuantPortfoliosPage = () => import('@/pages/market/quant/QuantPortfoliosPage.vue');
const ETFRotationPage = () => import('@/pages/market/ETFRotationPage.vue');
const TrendFollowingPage = () => import('@/pages/market/TrendFollowingPage.vue');
const CryptoBtcPage = () => import('@/pages/market/CryptoBtcPage.vue');
const LoginPage = () => import('@/pages/LoginPage.vue');
const TimelinePage = () => import('@/pages/TimelinePage.vue');
const ProfilePage = () => import('@/pages/ProfilePage.vue');
const TasksPage = () => import('@/pages/TasksPage.vue');
const NotFoundPage = () => import('@/pages/NotFoundPage.vue');

function redirectWithQuery(path: string) {
  return (to: RouteLocationGeneric) => ({
    path,
    query: to.query,
    hash: to.hash,
  });
}

function redirectLegacyQuant(to: RouteLocationGeneric) {
  const rest = to.params.pathMatch;
  const suffix = Array.isArray(rest) ? rest.filter(Boolean).join('/') : String(rest || '');
  return {
    path: suffix ? `/research/quant/${suffix}` : '/research/quant',
    query: to.query,
    hash: to.hash,
  };
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: Shell,
      children: [
        { path: 'notifications', name: 'notifications', component: () => import('@/pages/NotificationsPage.vue'), meta: { title: '消息中心' } },
        { path: '', redirect: { name: 'dashboard' } },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/pages/DashboardPage.vue'),
          meta: { title: '市场动态' },
        },
        { path: 'timeline', name: 'timeline', component: TimelinePage, meta: { title: '投资时间线' } },
        {
          path: 'research',
          component: ResearchPage,
          meta: { title: '研究' },
          children: [
            { path: '', redirect: { name: 'research-etf-rotation' } },
            {
              path: 'etf-rotation',
              name: 'research-etf-rotation',
              component: ETFRotationPage,
              meta: { title: 'ETF动量轮动' },
            },
            {
              path: 'trend-following',
              name: 'research-trend-following',
              component: TrendFollowingPage,
              meta: { title: '趋势跟踪' },
            },
            {
              path: 'quant',
              component: QuantPage,
              meta: { title: '量化研究' },
              children: [
                { path: '', name: 'research-quant', component: QuantDashboardPage },
                {
                  path: 'signals',
                  name: 'research-quant-signals',
                  component: QuantSignalsPage,
                  meta: { title: '模型选股' },
                },
                {
                  path: 'signals/:code',
                  name: 'research-quant-signal-detail',
                  component: QuantSignalDetailPage,
                  meta: { title: '选股详情' },
                },
                {
                  path: 'datasets',
                  name: 'research-quant-datasets',
                  component: QuantDatasetsPage,
                  meta: { title: '量化数据集' },
                },
                {
                  path: 'models',
                  name: 'research-quant-models',
                  component: QuantModelsPage,
                  meta: { title: '量化模型' },
                },
                {
                  path: 'models/:runId',
                  name: 'research-quant-model-run',
                  component: QuantModelRunPage,
                  meta: { title: '模型运行详情' },
                },
                {
                  path: 'portfolios',
                  name: 'research-quant-portfolios',
                  component: QuantPortfoliosPage,
                  meta: { title: '目标组合' },
                },
              ],
            },
            {
              path: 'crypto/btc',
              name: 'research-crypto-btc',
              component: CryptoBtcPage,
              meta: { title: 'BTC交易' },
            },
          ],
        },
        { path: 'analysis', name: 'analysis', component: HomePage, meta: { title: '分析' } },
        {
          path: 'market',
          component: MarketPage,
          meta: { title: '市场' },
          children: [
            { path: '', redirect: { name: 'market-watch-list' } },
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
              meta: { title: '投资组合' },
            },
          ],
        },
        { path: 'profile', redirect: { name: 'profile-info' }, meta: { title: '个人中心' } },
        { path: 'profile/info', name: 'profile-info', component: ProfilePage, meta: { title: '个人中心' } },
        { path: 'profile/password', name: 'profile-password', component: ProfilePage, meta: { title: '个人中心' } },
        {
          path: 'profile/notification',
          name: 'profile-notification',
          component: ProfilePage,
          meta: { title: '个人中心' },
        },
        { path: 'tasks', name: 'tasks', component: TasksPage, meta: { title: '任务中心' } },
        { path: 'tasks/scheduled', name: 'tasks-scheduled', component: TasksPage, meta: { title: '任务中心' } },
        { path: 'tasks/runs', name: 'tasks-runs', component: TasksPage, meta: { title: '任务中心' } },
        { path: 'chat', redirect: redirectWithQuery('/analysis') },
        { path: 'market/quant/:pathMatch(.*)*', redirect: redirectLegacyQuant },
        { path: 'market/etf-rotation', redirect: redirectWithQuery('/research/etf-rotation') },
        { path: 'market/trend-following', redirect: redirectWithQuery('/research/trend-following') },
        { path: 'market/crypto/btc', redirect: redirectWithQuery('/research/crypto/btc') },
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

router.beforeEach(async (to, from) => {
  if (
    to.path.startsWith('/research/quant')
    && from.path.startsWith('/research/quant')
    && to.query.market === undefined
    && (from.query.market === 'US' || from.query.market === 'CN')
  ) {
    return { path: to.path, params: to.params, query: { ...to.query, market: from.query.market }, replace: true };
  }
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
    return { path: '/dashboard', replace: true };
  }

  return true;
});

router.afterEach((to) => {
  document.title = resolveDocumentTitle(to);
});

export default router;

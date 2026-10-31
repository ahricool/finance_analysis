import { createRouter, createWebHistory, type RouteLocationGeneric, type RouteLocationNormalizedLoaded } from 'vue-router';
import { isAppMarket, useMarketStore } from '@/stores/marketStore';
import Shell from '@/components/layout/Shell.vue';
import { formatDocumentTitle } from '@/config/app';
import { useAuthStore } from '@/stores/authStore';
import { installChunkReload } from './chunkReload';

declare module 'vue-router' {
  interface RouteMeta {
    public?: boolean;
    title?: string;
    marketScope?: 'selectable' | 'CN' | 'US';
  }
}

const MarketPage = () => import('@/pages/MarketPage.vue');
const CryptoPage = () => import('@/pages/CryptoPage.vue');
const ResearchPage = () => import('@/pages/ResearchPage.vue');
const MarketWatchListPage = () => import('@/pages/WatchListPage.vue');
const MarketHoldingsPage = () => import('@/pages/market/HoldingsPage.vue');
const QuantPage = () => import('@/pages/market/QuantPage.vue');
const QuantDashboardPage = () => import('@/pages/market/quant/QuantDashboardPage.vue');
const QuantSignalsPage = () => import('@/pages/market/quant/QuantSignalsPage.vue');
const QuantSignalDetailPage = () => import('@/pages/market/quant/QuantSignalDetailPage.vue');
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
        { path: 'strategies', name: 'strategies', component: () => import('@/pages/StockStrategiesPage.vue'), meta: { title: '策略模拟', marketScope: 'selectable' } },
        { path: 'strategies/:strategyKey', name: 'strategy-detail', component: () => import('@/pages/StockStrategiesPage.vue'), meta: { title: '策略详情', marketScope: 'selectable' } },
        { path: 'notifications', name: 'notifications', component: () => import('@/pages/NotificationsPage.vue'), meta: { title: '消息中心' } },
        { path: '', redirect: { name: 'dashboard' } },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/pages/DashboardPage.vue'),
          meta: { title: '市场动态' },
        },
        {
          path: 'crypto',
          component: CryptoPage,
          children: [
            { path: '', redirect: redirectWithQuery('/crypto/btc') },
            { path: 'btc', name: 'crypto-btc', component: CryptoBtcPage, meta: { title: 'BTC交易' } },
          ],
        },
        { path: 'research/crypto/btc', name: 'research-crypto-btc', redirect: redirectWithQuery('/crypto/btc') },
        { path: 'timeline', name: 'timeline', component: TimelinePage, meta: { title: '投资时间线', marketScope: 'selectable' } },
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
              meta: { title: 'ETF动量轮动', marketScope: 'selectable' },
            },
            {
              path: 'trend-following',
              name: 'research-trend-following',
              component: TrendFollowingPage,
              meta: { title: '趋势跟踪', marketScope: 'selectable' },
            },
            { path: 'intraday-confirmation', name: 'research-intraday-confirmation', component: () => import('@/pages/market/IntradayConfirmationPage.vue'), meta: { title: '盘中确认', marketScope: 'selectable' } },
            { path: 'options-intelligence', name: 'research-options-intelligence', component: () => import('@/pages/market/OptionsIntelligencePage.vue'), meta: { title: '期权情报', marketScope: 'US' } },
            { path: 'signal-center', name: 'research-signal-center', component: () => import('@/pages/market/SignalCenterPage.vue'), meta: { title: '信号中心', marketScope: 'selectable' } },
            { path: 'confluence', name: 'research-confluence', component: () => import('@/pages/market/ConfluencePage.vue'), meta: { title: '多信号共振', marketScope: 'selectable' } },
            { path: 'industry-strength', name: 'research-industry-strength', component: () => import('@/pages/market/IndustryStrengthPage.vue'), meta: { title: '行业强度', marketScope: 'CN' } },
            { path: 'dragon-tiger-flow', name: 'research-dragon-tiger-flow', component: () => import('@/pages/market/DragonTigerFlowPage.vue'), meta: { title: '龙虎榜资金流向', marketScope: 'CN' } },
            { path: 'market-sentiment', name: 'research-market-sentiment', component: () => import('@/pages/market/MarketSentimentPage.vue'), meta: { title: '市场情绪', marketScope: 'CN' } },
            { path: 'macro', name: 'research-macro', component: () => import('@/pages/market/MacroPage.vue'), meta: { title: '宏观数据', marketScope: 'US' } },
            {
              path: 'quant',
              component: QuantPage,
              meta: { title: '量化研究', marketScope: 'selectable' },
              children: [
                { path: '', name: 'research-quant', component: QuantDashboardPage },
                {
                  path: 'signals',
                  name: 'research-quant-signals',
                  component: QuantSignalsPage,
                  meta: { title: '个股排名' },
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
                  redirect: to => ({ path: '/research/quant/models', query: to.query }),
                },
                {
                  path: 'models',
                  name: 'research-quant-models',
                  component: QuantModelsPage,
                  meta: { title: '量化模型管理', admin: true },
                },
                {
                  path: 'models/:runId',
                  name: 'research-quant-model-run',
                  component: QuantModelRunPage,
                  meta: { title: '模型运行详情', admin: true },
                },
                {
                  path: 'portfolios',
                  name: 'research-quant-portfolios',
                  component: QuantPortfoliosPage,
                  meta: { title: '目标组合' },
                },
              ],
            },
          ],
        },
        {
          path: 'market',
          component: MarketPage,
          meta: { title: '市场' },
          children: [
            { path: '', redirect: { name: 'market-watch-list' } },
            { path: 'holdings-review', name: 'market-holdings-review', component: () => import('@/pages/market/HoldingsReviewPage.vue'), meta: { title: '持仓复盘', marketScope: 'selectable' } },
            { path: 'heatmap', name: 'market-heatmap', component: () => import('@/pages/market/MarketHeatmapPage.vue'), meta: { title: '热力图', marketScope: 'selectable' } },
            {
              path: 'watch-list',
              name: 'market-watch-list',
              component: MarketWatchListPage,
              meta: { title: '自选股', marketScope: 'selectable' },
            },
            {
              path: 'holdings',
              name: 'market-holdings',
              component: MarketHoldingsPage,
              meta: { title: '投资组合', marketScope: 'selectable' },
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
        { path: 'chat', redirect: redirectWithQuery('/dashboard') },
        { path: 'market/quant/:pathMatch(.*)*', redirect: redirectLegacyQuant },
        { path: 'market/etf-rotation', redirect: redirectWithQuery('/research/etf-rotation') },
        { path: 'market/trend-following', redirect: redirectWithQuery('/research/trend-following') },
        { path: 'market/crypto/btc', redirect: redirectWithQuery('/crypto/btc') },
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

  if (to.meta.admin && auth.currentUser?.role !== 'admin') return { path: '/research/quant', query: { market: to.query.market } };

  if (to.path === '/login' && auth.loggedIn) {
    return { path: '/dashboard', replace: true };
  }

  if (to.meta.marketScope === 'selectable'
    && (to.query.market !== undefined || to.path.startsWith('/research/quant'))
    && !isAppMarket(to.query.market)) {
    return { path: to.path, query: { ...to.query, market: useMarketStore().market }, hash: to.hash, replace: true };
  }

  return true;
});

router.afterEach((to) => {
  document.title = resolveDocumentTitle(to);
});

installChunkReload(router);


router.afterEach((to, _from, failure) => {
  if (!failure && to.meta.marketScope === 'selectable' && isAppMarket(to.query.market)) {
    useMarketStore().setMarket(to.query.market);
  }
});

export default router;

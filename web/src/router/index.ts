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
const BacktestPage = () => import('@/pages/BacktestPage.vue');
const WatchListPage = () => import('@/pages/WatchListPage.vue');
const StockListPage = () => import('@/pages/StockListPage.vue');
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
        { path: 'watch-list', name: 'watch-list', component: WatchListPage, meta: { title: '自选股' } },
        { path: 'stock-list', name: 'stock-list', component: StockListPage, meta: { title: '持仓股' } },
        { path: 'backtest', name: 'backtest', component: BacktestPage, meta: { title: '策略回测' } },
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

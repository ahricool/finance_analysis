import { createRouter, createWebHistory } from 'vue-router';
import Shell from '@/components/layout/Shell.vue';
import HomePage from '@/pages/HomePage.vue';
import ChatPage from '@/pages/ChatPage.vue';
import PortfolioPage from '@/pages/PortfolioPage.vue';
import BacktestPage from '@/pages/BacktestPage.vue';
import WatchListPage from '@/pages/WatchListPage.vue';
import StockListPage from '@/pages/StockListPage.vue';
import LoginPage from '@/pages/LoginPage.vue';
import CalendarPage from '@/pages/CalendarPage.vue';
import NotFoundPage from '@/pages/NotFoundPage.vue';
import { useAuthStore } from '@/stores/authStore';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: Shell,
      children: [
        { path: '', name: 'home', component: HomePage },
        { path: 'chat', name: 'chat', component: ChatPage },
        { path: 'watch-list', name: 'watch-list', component: WatchListPage },
        { path: 'stock-list', name: 'stock-list', component: StockListPage },
        { path: 'portfolio', name: 'portfolio', component: PortfolioPage },
        { path: 'backtest', name: 'backtest', component: BacktestPage },
        { path: 'calendar', name: 'calendar', component: CalendarPage },
        { path: ':pathMatch(.*)*', name: 'not-found', component: NotFoundPage },
      ],
    },
    { path: '/login', name: 'login', component: LoginPage, meta: { public: true } },
  ],
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (auth.isLoading) {
    await auth.fetchStatus();
  }

  const isPublic = to.meta.public === true;
  if (auth.authEnabled && !auth.loggedIn && !isPublic) {
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

export default router;

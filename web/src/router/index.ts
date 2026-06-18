import { createRouter, createWebHistory } from 'vue-router';
import Shell from '@/components/layout/Shell.vue';
import { useAuthStore } from '@/stores/authStore';

const HomePage = () => import('@/pages/HomePage.vue');
const ChatPage = () => import('@/pages/ChatPage.vue');
const BacktestPage = () => import('@/pages/BacktestPage.vue');
const WatchListPage = () => import('@/pages/WatchListPage.vue');
const StockListPage = () => import('@/pages/StockListPage.vue');
const LoginPage = () => import('@/pages/LoginPage.vue');
const CalendarPage = () => import('@/pages/CalendarPage.vue');
const ProfilePage = () => import('@/pages/ProfilePage.vue');
const NotFoundPage = () => import('@/pages/NotFoundPage.vue');

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
        { path: 'backtest', name: 'backtest', component: BacktestPage },
        { path: 'calendar', name: 'calendar', component: CalendarPage },
        { path: 'profile', name: 'profile', component: ProfilePage },
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

export default router;

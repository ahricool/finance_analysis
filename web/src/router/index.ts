import { createRouter, createWebHistory } from 'vue-router';
import Shell from '@/components/layout/Shell.vue';
import HomePage from '@/pages/HomePage.vue';
import ChatPage from '@/pages/ChatPage.vue';
import PortfolioPage from '@/pages/PortfolioPage.vue';
import BacktestPage from '@/pages/BacktestPage.vue';
import SettingsPage from '@/pages/SettingsPage.vue';
import WatchListPage from '@/pages/WatchListPage.vue';
import StockListPage from '@/pages/StockListPage.vue';
import LoginPage from '@/pages/LoginPage.vue';
import NotFoundPage from '@/pages/NotFoundPage.vue';

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
        { path: 'settings', name: 'settings', component: SettingsPage },
        { path: ':pathMatch(.*)*', name: 'not-found', component: NotFoundPage },
      ],
    },
    { path: '/login', name: 'login', component: LoginPage },
  ],
});

export default router;

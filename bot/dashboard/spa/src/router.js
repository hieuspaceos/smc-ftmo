import { createRouter, createWebHistory } from 'vue-router';
import LiveQueueView from './views/LiveQueueView.vue';
import ExecutionView from './views/ExecutionView.vue';
import ReplayView from './views/ReplayView.vue';
import AuditView from './views/AuditView.vue';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/live' },
    { path: '/live', component: LiveQueueView, name: 'live', meta: { title: 'Live Queue' } },
    { path: '/execution', component: ExecutionView, name: 'execution', meta: { title: 'Execution Log' } },
    { path: '/replay', component: ReplayView, name: 'replay', meta: { title: 'Replay' } },
    { path: '/audit', component: AuditView, name: 'audit', meta: { title: 'Audit' } },
  ],
});

router.afterEach((to) => {
  const base = 'SMC Bot Admin';
  document.title = to.meta?.title ? `${to.meta.title} — ${base}` : base;
});

export default router;

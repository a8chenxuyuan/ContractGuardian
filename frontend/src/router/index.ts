import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true, title: '登录' },
    },
    {
      path: '/register',
      name: 'Register',
      component: () => import('@/views/RegisterView.vue'),
      meta: { public: true, title: '注册' },
    },
    {
      path: '/share/:token',
      name: 'Share',
      component: () => import('@/views/ShareView.vue'),
      props: true,
      meta: { public: true, title: '报告分享' },
    },
    {
      path: '/',
      component: () => import('@/layouts/AppLayout.vue'),
      children: [
        {
          path: '',
          redirect: '/contracts',
        },
        {
          path: 'contracts',
          name: 'Contracts',
          component: () => import('@/views/ContractListView.vue'),
          meta: { title: '合同工作台' },
        },
        {
          path: 'upload',
          name: 'Upload',
          component: () => import('@/views/UploadView.vue'),
          meta: { title: '上传合同' },
        },
        {
          path: 'dashboard',
          name: 'Dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: '风险台账看板' },
        },
        {
          path: 'calendar',
          name: 'Calendar',
          component: () => import('@/views/CalendarView.vue'),
          meta: { title: '履约日历' },
        },
        {
          path: 'notifications',
          name: 'Notifications',
          component: () => import('@/views/NotificationsView.vue'),
          meta: { title: '通知中心' },
        },
        {
          path: 'knowledge',
          name: 'Knowledge',
          component: () => import('@/views/KnowledgeView.vue'),
          meta: { title: '法规知识库' },
        },
        {
          path: 'templates',
          name: 'Templates',
          component: () => import('@/views/TemplatesView.vue'),
          meta: { title: '合同模板库' },
        },
        {
          path: 'report/:contractId/:sessionId',
          name: 'Report',
          component: () => import('@/views/ReportView.vue'),
          props: true,
          meta: { title: '审查报告' },
        },
        {
          path: 'profile',
          name: 'Profile',
          component: () => import('@/views/ProfileView.vue'),
          meta: { title: '个人中心' },
        },
        {
          path: 'membership',
          name: 'Membership',
          component: () => import('@/views/MembershipView.vue'),
          meta: { title: '会员中心' },
        },
        {
          path: 'admin',
          name: 'Admin',
          component: () => import('@/views/AdminView.vue'),
          meta: { title: '管理后台', requiresAdmin: true },
        },
      ],
    },
  ],
})

router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore()
  const parent = to.matched.find((r) => r.meta?.title) || to
  const title = (parent.meta?.title as string) || (to.meta?.title as string)
  if (title) {
    document.title = `${title} · 合同卫士`
  } else {
    document.title = '合同卫士 · AI 合同审查平台'
  }

  // 刷新后 store 中无用户信息，用 token 兜底恢复
  if (authStore.token && !authStore.user) {
    await authStore.fetchMe()
  }

  if (!to.matched.some((r) => r.meta.public) && !authStore.token) {
    next('/login')
  } else if (to.meta.requiresAdmin && !authStore.isAdmin) {
    next('/contracts')
  } else {
    next()
  }
})

export default router

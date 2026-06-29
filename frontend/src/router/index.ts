import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const LoginView = () => import('../views/LoginView.vue')
const PortalView = () => import('../views/PortalView.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/platform', name: 'platform', component: PortalView, meta: { identity: 'PLATFORM' } },
    { path: '/customer', name: 'customer', component: PortalView, meta: { identity: 'CUSTOMER' } },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()

  // 未登录访问需要认证的页面 -> 跳转登录
  if (!to.meta.public && !auth.isLoggedIn) {
    return '/login'
  }

  // 已登录访问登录页 -> 跳转到门户
  if (to.path === '/login' && auth.isLoggedIn) {
    return auth.portalPath
  }

  // 检查身份类型是否匹配
  const requiredIdentity = to.meta.identity as string | undefined
  if (requiredIdentity && auth.session?.identity?.identity_type !== requiredIdentity) {
    return auth.portalPath
  }

  // 允许导航
})

export default router

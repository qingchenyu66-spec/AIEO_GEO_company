import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const LoginView = () => import('../views/LoginView.vue')
const ChangePasswordView = () => import('../views/ChangePasswordView.vue')
const PortalView = () => import('../views/PortalView.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/change-password', name: 'change-password', component: ChangePasswordView },
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

  // 已登录访问登录页 -> 跳转到门户或强制改密
  if (to.path === '/login' && auth.isLoggedIn) {
    return auth.mustChangePassword ? '/change-password' : auth.portalPath
  }

  // 2026-07-31 - 强制改密闸门 - 未改密只能停在改密页
  if (auth.isLoggedIn && auth.mustChangePassword && to.path !== '/change-password') {
    return '/change-password'
  }
  if (auth.isLoggedIn && !auth.mustChangePassword && to.path === '/change-password') {
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

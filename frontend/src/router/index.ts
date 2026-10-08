import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const LoginView = () => import('../views/LoginView.vue')
const ChangePasswordView = () => import('../views/ChangePasswordView.vue')
const AccountView = () => import('../views/AccountView.vue')
const PortalView = () => import('../views/PortalView.vue')
const H5DiagnosisLandingPage = () => import('../views/h5/H5DiagnosisLandingPage.vue')
const H5DiagnosisApplyPage = () => import('../views/h5/H5DiagnosisApplyPage.vue')
const H5DiagnosisResultPage = () => import('../views/h5/H5DiagnosisResultPage.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
    { path: '/h5/diagnosis', name: 'h5-diagnosis', component: H5DiagnosisLandingPage, meta: { public: true } },
    { path: '/h5/diagnosis/apply', name: 'h5-diagnosis-apply', component: H5DiagnosisApplyPage, meta: { public: true } },
    { path: '/h5/diagnosis/result', name: 'h5-diagnosis-result', component: H5DiagnosisResultPage, meta: { public: true } },
    { path: '/change-password', name: 'change-password', component: ChangePasswordView },
    { path: '/account', name: 'account', component: AccountView },
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

  // 已登录访问登录页 -> 进门户. 改密页仍可从顶栏主动进入
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

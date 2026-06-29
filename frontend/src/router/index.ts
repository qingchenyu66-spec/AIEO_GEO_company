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
  if (!to.meta.public && !auth.isLoggedIn) return '/login'
  if (to.path === '/login' && auth.isLoggedIn) return auth.portalPath
  const requiredIdentity = to.meta.identity
  if (requiredIdentity && auth.session?.identity.identity_type !== requiredIdentity) return auth.portalPath
})

export default router

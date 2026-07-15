import { defineStore } from 'pinia'
import {
  loginApi, logoutApi, meApi, selectIdentityApi, switchIdentityApi,
  type AuthSession, type IdentityInfo, type UserInfo,
} from '../services/auth'

const STORAGE_KEY = 'geo-auth-session'

function stripToken(session: AuthSession): AuthSession {
  const { access_token: _token, token_type: _type, ...rest } = session
  return rest as AuthSession
}

function readSession(): AuthSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const session = JSON.parse(raw)
    if (!session || !session.identity) {
      localStorage.removeItem(STORAGE_KEY)
      return null
    }
    return session as AuthSession
  }
  catch {
    localStorage.removeItem(STORAGE_KEY)
    return null
  }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    session: readSession() as AuthSession | null,
    pendingTicket: '',
    pendingUser: null as UserInfo | null,
    pendingIdentities: [] as IdentityInfo[],
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.session?.identity),
    portalPath: (state) => state.session?.identity.identity_type === 'PLATFORM' ? '/platform' : '/customer',
    allowedMenus: (state) => state.session?.menus || [],
  },
  actions: {
    saveSession(session: AuthSession) {
      this.session = session
      localStorage.setItem(STORAGE_KEY, JSON.stringify(stripToken(session)))
      this.pendingTicket = ''
      this.pendingUser = null
      this.pendingIdentities = []
    },
    async login(username: string, password: string) {
      const result = await loginApi(username, password)
      if (result.session) this.saveSession(result.session)
      else {
        this.pendingTicket = result.ticket || ''
        this.pendingUser = result.user || null
        this.pendingIdentities = result.identities || []
      }
      return result.requires_identity_selection
    },
    async selectIdentity(identityId: number) {
      const session = await selectIdentityApi(this.pendingTicket, identityId)
      this.saveSession(session)
    },
    async switchIdentity(identityId: number) {
      const session = await switchIdentityApi(identityId)
      this.saveSession(session)
    },
    async refreshSession() {
      if (!this.session?.identity) return
      const latest = await meApi()
      this.saveSession(latest)
    },
    async logout() {
      // 先调服务端（仍带当前 Bearer/Cookie），再清本地，便于审计记到真实操作人
      try {
        await logoutApi()
      } catch {
        // 网络异常时仍清本地态
      }
      this.session = null
      this.pendingTicket = ''
      this.pendingIdentities = []
      localStorage.removeItem(STORAGE_KEY)
    },
  },
})

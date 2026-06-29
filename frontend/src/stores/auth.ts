import { defineStore } from 'pinia'
import {
  loginApi, meApi, selectIdentityApi, switchIdentityApi,
  type AuthSession, type IdentityInfo, type UserInfo,
} from '../services/auth'

const STORAGE_KEY = 'geo-auth-session'

function readSession(): AuthSession | null {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null') }
  catch { return null }
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    session: readSession() as AuthSession | null,
    pendingTicket: '',
    pendingUser: null as UserInfo | null,
    pendingIdentities: [] as IdentityInfo[],
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.session?.access_token),
    portalPath: (state) => state.session?.identity.identity_type === 'PLATFORM' ? '/platform' : '/customer',
    allowedMenus: (state) => state.session?.menus || [],
  },
  actions: {
    saveSession(session: AuthSession) {
      this.session = session
      localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
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
      if (!this.session?.access_token) return
      const latest = await meApi()
      this.saveSession({
        ...latest,
        access_token: this.session.access_token,
        token_type: this.session.token_type,
      })
    },
    logout() {
      this.session = null
      this.pendingTicket = ''
      this.pendingIdentities = []
      localStorage.removeItem(STORAGE_KEY)
    },
  },
})

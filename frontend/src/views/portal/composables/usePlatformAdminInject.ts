import { inject } from 'vue'
import { PlatformAdminKey } from '../injectionKeys'
import type { PlatformAdminContext } from '../composables/usePlatformAdmin'

export function usePlatformAdminInject(): PlatformAdminContext {
  const admin = inject(PlatformAdminKey)
  if (!admin) throw new Error('PlatformAdminKey is not provided')
  return admin
}

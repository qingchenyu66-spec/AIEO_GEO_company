import { computed, ref, watch, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { MenuInfo } from '../../../services/auth'

export const MENU_FAVORITES_MAX = 5
const STORAGE_PREFIX = 'geo.portal.menuFavorites'

export function menuFavoritesStorageKey(userId: number, identityId: number) {
  return `${STORAGE_PREFIX}:${userId}:${identityId}`
}

export function readMenuFavorites(userId: number, identityId: number): string[] {
  try {
    const raw = localStorage.getItem(menuFavoritesStorageKey(userId, identityId))
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

export function writeMenuFavorites(userId: number, identityId: number, codes: string[]) {
  localStorage.setItem(menuFavoritesStorageKey(userId, identityId), JSON.stringify(codes))
}

/** 置顶项按收藏顺序排前，其余保持原序；无效 code 自动剔除。 */
export function partitionMenusByFavorites(menus: MenuInfo[], favorites: string[]) {
  const byCode = new Map(menus.map(menu => [menu.menu_code, menu]))
  const pinnedCodes = favorites.filter(code => byCode.has(code))
  const pinned = pinnedCodes.map(code => byCode.get(code)!)
  const pinnedSet = new Set(pinnedCodes)
  const rest = menus.filter(menu => !pinnedSet.has(menu.menu_code))
  return { pinned, rest, pinnedCodes }
}

function selfcheckPartitionMenusByFavorites() {
  const menus = [
    { id: 1, menu_code: 'a', menu_name: 'A', identity_type: 'PLATFORM', route_path: '', icon: '', sort_order: 1, can_create: false, can_update: false, can_delete: false, can_export: false },
    { id: 2, menu_code: 'b', menu_name: 'B', identity_type: 'PLATFORM', route_path: '', icon: '', sort_order: 2, can_create: false, can_update: false, can_delete: false, can_export: false },
    { id: 3, menu_code: 'c', menu_name: 'C', identity_type: 'PLATFORM', route_path: '', icon: '', sort_order: 3, can_create: false, can_update: false, can_delete: false, can_export: false },
  ] satisfies MenuInfo[]
  const { pinned, rest } = partitionMenusByFavorites(menus, ['b', 'missing'])
  if (pinned.length !== 1 || pinned[0]?.menu_code !== 'b' || rest.length !== 2) {
    throw new Error('partitionMenusByFavorites selfcheck failed')
  }
}

if (import.meta.env.DEV) {
  selfcheckPartitionMenusByFavorites()
}

export function useMenuFavorites(
  userId: Ref<number | undefined>,
  identityId: Ref<number | undefined>,
  menus: Ref<MenuInfo[]>,
  enabled: Ref<boolean>,
) {
  const favorites = ref<string[]>([])

  function load() {
    if (!enabled.value || !userId.value || !identityId.value) {
      favorites.value = []
      return
    }
    favorites.value = readMenuFavorites(userId.value, identityId.value)
  }

  function persist(next: string[]) {
    favorites.value = next
    if (enabled.value && userId.value && identityId.value) {
      writeMenuFavorites(userId.value, identityId.value, next)
    }
  }

  function pruneInvalid() {
    const allowed = new Set(menus.value.map(menu => menu.menu_code))
    const next = favorites.value.filter(code => allowed.has(code))
    if (next.length !== favorites.value.length) {
      persist(next)
    }
  }

  function isMenuPinned(menuCode: string) {
    return favorites.value.includes(menuCode)
  }

  function toggleMenuPin(menuCode: string) {
    if (!enabled.value) return
    if (isMenuPinned(menuCode)) {
      persist(favorites.value.filter(code => code !== menuCode))
      return
    }
    if (favorites.value.length >= MENU_FAVORITES_MAX) {
      ElMessage.warning(`最多置顶 ${MENU_FAVORITES_MAX} 个菜单`)
      return
    }
    persist([...favorites.value, menuCode])
  }

  const sidebarMenus = computed(() => partitionMenusByFavorites(menus.value, favorites.value))

  const displayMenus = computed(() => [...sidebarMenus.value.pinned, ...sidebarMenus.value.rest])

  const pinnedMenuCount = computed(() => sidebarMenus.value.pinned.length)

  watch([userId, identityId, enabled], load, { immediate: true })
  watch(menus, pruneInvalid)

  return {
    favorites,
    isMenuPinned,
    toggleMenuPin,
    displayMenus,
    pinnedMenuCount,
  }
}

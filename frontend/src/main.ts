import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { ElDialog, ElDropdown, ElDropdownItem, ElDropdownMenu, ElTooltip } from 'element-plus'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/dropdown/style/css'
import 'element-plus/es/components/dropdown-menu/style/css'
import 'element-plus/es/components/dropdown-item/style/css'
import 'element-plus/es/components/tooltip/style/css'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import './style.css'
import './styles/customer-workspace.css'
import './styles/workspace-campus.css'
import './styles/workspace-board.css'
import './styles/monitor-realtime.css'
import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import { startSessionKeepAlive } from './utils/sessionKeepAlive'
import { applyPlatformFaviconFromServer } from './utils/platformFavicon'

void applyPlatformFaviconFromServer()

const app = createApp(App)

const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(ElDialog)
app.use(ElDropdown)
app.use(ElDropdownMenu)
app.use(ElDropdownItem)
app.use(ElTooltip)
app.mount('#app')

if (useAuthStore().isLoggedIn) {
  startSessionKeepAlive()
}

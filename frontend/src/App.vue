<template>
  <router-view />
  <div v-if="loadingStore.isLoading" class="global-loading">
    <div class="loading-spinner"></div>
  </div>
</template>

<script setup lang="ts">
import { useLoadingStore } from './stores/loading'

const loadingStore = useLoadingStore()
</script>

<style scoped>
.global-loading {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #409eff 0%, #66b1ff 50%, #409eff 100%);
  z-index: 9999;
  animation: loading-progress 1.5s ease-in-out infinite;
}

.loading-spinner {
  width: 100%;
  height: 100%;
  background: repeating-linear-gradient(
    -45deg,
    transparent,
    transparent 10px,
    rgba(255, 255, 255, 0.3) 10px,
    rgba(255, 255, 255, 0.3) 20px
  );
  animation: loading-stripe 1s linear infinite;
}

@keyframes loading-progress {
  0% { opacity: 0.6; }
  50% { opacity: 1; }
  100% { opacity: 0.6; }
}

@keyframes loading-stripe {
  0% { background-position: 0 0; }
  100% { background-position: 28px 0; }
}
</style>

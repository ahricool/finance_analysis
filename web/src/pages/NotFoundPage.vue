<script setup lang="ts">
import { useRouter } from 'vue-router';

const router = useRouter();
</script>

<template>
  <div class="flex min-h-screen flex-col items-center justify-center px-4 text-center">
    <div class="relative mb-8">
      <span class="gradient-text font-display text-8xl">
        404
      </span>
    </div>

    <h1 class="mb-2 text-2xl font-bold text-foreground">页面未找到</h1>
    <p class="mb-8 text-muted-text">抱歉，您访问的页面不存在或已被移动</p>

    <button type="button" class="btn-primary flex items-center gap-2" @click="router.push('/analysis')">
      <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          stroke-width="2"
          d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"
        />
      </svg>
      返回分析
    </button>
  </div>
</template>

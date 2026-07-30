<script setup lang="ts">
import { useRouter } from 'vue-router';
import { House } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';

const router = useRouter();
</script>

<template>
  <div class="flex min-h-screen flex-col items-center justify-center px-4 text-center">
    <div class="relative mb-8">
      <span class="gradient-text font-display text-8xl"> 404 </span>
    </div>

    <h1 class="mb-2 text-2xl font-bold text-foreground">
      页面未找到
    </h1>
    <p class="mb-8 text-muted-foreground">
      抱歉，您访问的页面不存在或已被移动
    </p>

    <Button @click="router.push('/analysis')">
      <House />
      返回分析
    </Button>
  </div>
</template>

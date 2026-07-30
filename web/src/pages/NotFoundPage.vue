<script setup lang="ts">
import { useRouter } from 'vue-router';
import { House } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';

const router = useRouter();
</script>

<template>
  <div class="flex min-h-[70vh] flex-col items-center justify-center px-4 text-center">
    <p class="mb-8 text-8xl font-semibold tracking-tight text-muted-foreground/40">
      404
    </p>

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

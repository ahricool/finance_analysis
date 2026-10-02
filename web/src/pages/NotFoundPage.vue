<script setup lang="ts">
import { useRouter } from 'vue-router';
import { ArrowLeft, House } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';

const router = useRouter();
</script>

<template>
  <div class="flex min-h-[70vh] flex-col items-center justify-center px-4 text-center animate-in fade-in duration-500">
    <p
      class="mb-6 bg-gradient-to-b from-muted-foreground/30 to-muted-foreground/10 bg-clip-text text-8xl font-semibold tracking-tight text-transparent"
      aria-hidden="true"
    >
      404
    </p>

    <h1 class="mb-2 text-2xl font-semibold tracking-tight text-foreground">
      页面未找到
    </h1>
    <p class="mb-8 max-w-md text-sm leading-relaxed text-muted-foreground">
      抱歉，您访问的页面不存在或已被移动。请检查地址，或返回市场动态继续浏览。
    </p>

    <div class="flex flex-wrap items-center justify-center gap-3">
      <Button
        variant="outline"
        @click="router.back()"
      >
        <ArrowLeft />
        返回上一页
      </Button>
      <Button
        variant="brand"
        @click="router.push('/dashboard')"
      >
        <House />
        返回动态
      </Button>
    </div>
  </div>
</template>

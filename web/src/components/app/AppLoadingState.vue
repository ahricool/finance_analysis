<script setup lang="ts">import { LoaderCircle } from 'lucide-vue-next'; withDefaults(defineProps<{ label?: string }>(), { label: '加载中…' });</script>
<template><div class="flex min-h-32 flex-col items-center justify-center gap-3 rounded-xl border border-dashed text-sm text-muted-foreground"><LoaderCircle class="size-5 animate-spin text-primary" />{{ label }}</div></template>

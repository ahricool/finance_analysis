<script setup lang="ts">
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
withDefaults(defineProps<{
  open: boolean; title: string; description: string; confirmText?: string; cancelText?: string; destructive?: boolean;
}>(), { confirmText: '确定', cancelText: '取消', destructive: false });
const emit = defineEmits<{ 'update:open': [value: boolean]; confirm: [] }>();
</script>

<template>
  <AlertDialog :open="open" @update:open="emit('update:open', $event)">
    <AlertDialogContent class="max-w-[calc(100%-2rem)] sm:max-w-md">
      <AlertDialogHeader><AlertDialogTitle>{{ title }}</AlertDialogTitle><AlertDialogDescription>{{ description }}</AlertDialogDescription></AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>{{ cancelText }}</AlertDialogCancel>
        <AlertDialogAction :class="destructive ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90' : ''" @click="emit('confirm')">{{ confirmText }}</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
</template>

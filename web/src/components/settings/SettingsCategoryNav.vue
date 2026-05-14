<script setup lang="ts">
import Badge from '@/components/common/Badge.vue';
import { cn } from '@/utils/cn';
import type { SystemConfigCategorySchema, SystemConfigItem } from '@/types/systemConfig';
import { getCategoryDescriptionZh, getCategoryTitleZh } from '@/utils/systemConfigI18n';

defineProps<{
  categories: SystemConfigCategorySchema[];
  itemsByCategory: Record<string, SystemConfigItem[]>;
  activeCategory: string;
}>();

const emit = defineEmits<{
  select: [category: string];
}>();
</script>

<template>
  <div class="h-full rounded-[1.5rem] border settings-border bg-card/94 p-4 shadow-soft-card-strong backdrop-blur-sm">
    <div class="mb-4">
      <p class="settings-accent-text text-xs font-semibold uppercase tracking-[0.3em]">配置分类</p>
      <p class="mt-1 text-[11px] leading-relaxed text-muted-text">按模块整理系统设置与认证能力。</p>
    </div>

    <div class="space-y-2.5">
      <button
        v-for="category in categories"
        :key="category.category"
        type="button"
        :class="
          cn(
            'w-full rounded-[1.1rem] border px-3 py-3 text-left transition-[background-color,border-color,box-shadow,transform] duration-200',
            category.category === activeCategory
              ? 'settings-nav-item-active'
              : 'border-[var(--settings-border)] bg-[var(--settings-surface)] hover:border-[hsl(var(--primary)/0.32)] hover:bg-[hsl(var(--primary)/0.045)]',
          )
        "
        @click="emit('select', category.category)"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p
              :class="
                cn(
                  'text-sm font-semibold tracking-tight',
                  category.category === activeCategory ? 'text-foreground' : 'text-secondary-text',
                )
              "
            >
              {{ getCategoryTitleZh(category.category, category.title) }}
            </p>
            <p
              v-if="getCategoryDescriptionZh(category.category, category.description)"
              :class="
                cn(
                  'mt-1 line-clamp-2 text-xs leading-5',
                  category.category === activeCategory ? 'text-secondary-text' : 'text-muted-text',
                )
              "
            >
              {{ getCategoryDescriptionZh(category.category, category.description) }}
            </p>
          </div>
          <Badge
            :variant="category.category === activeCategory ? 'info' : 'default'"
            size="sm"
            :class="
              category.category === activeCategory
                ? 'settings-accent-badge border-[hsl(var(--primary)/0.36)]'
                : 'border-[var(--settings-border)] bg-[var(--settings-surface-hover)] text-muted-text'
            "
          >
            {{ (itemsByCategory[category.category] || []).length }}
          </Badge>
        </div>
      </button>
    </div>
  </div>
</template>

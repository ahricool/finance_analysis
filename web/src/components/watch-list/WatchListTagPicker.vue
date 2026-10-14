<script setup lang="ts">
import { computed, ref } from 'vue';
import { X, Plus, Check } from 'lucide-vue-next';
import type { WatchListTag, WatchListTagDraft } from '@/api/watchList';
import FieldInput from '@/components/forms/FieldInput.vue';
import { Button } from '@/components/ui/button';

const props = defineProps<{ modelValue: WatchListTagDraft[]; tags: WatchListTag[]; disabled?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [value: WatchListTagDraft[]] }>();
const query = ref('');
const name = computed(() => query.value.trim());
const key = (value: string) => value.toLocaleLowerCase();
const matching = computed(() => props.tags.filter(tag => key(tag.name).includes(key(name.value))));
const canCreate = computed(() => name.value.length > 0 && [...name.value].length <= 32
  && ![...props.tags, ...props.modelValue].some(tag => key(tag.name) === key(name.value)));
const selected = (tag: WatchListTag) => props.modelValue.some(value => value.id === tag.id);
function toggle(tag: WatchListTag) {
  emit('update:modelValue', selected(tag)
    ? props.modelValue.filter(value => value.id !== tag.id)
    : [...props.modelValue, { ...tag }]);
}
function create() {
  if (!canCreate.value || props.modelValue.length >= 50) return;
  emit('update:modelValue', [...props.modelValue, { name: name.value }]);
  query.value = '';
}
</script>

<template>
  <div
    class="grid min-w-0 gap-2"
    data-testid="tag-picker"
  >
    <FieldInput
      v-model="query"
      label="分组标签"
      placeholder="搜索或输入新标签名称"
      :disabled="disabled"
      @keydown.enter.prevent="create"
    />
    <div
      v-if="modelValue.length"
      class="flex flex-wrap gap-1"
    >
      <Button
        v-for="(tag, index) in modelValue"
        :key="tag.id ?? tag.name"
        variant="secondary"
        size="sm"
        class="h-auto max-w-full gap-1 px-2 py-1 text-xs"
        :disabled="disabled"
        :aria-label="`移除标签 ${tag.name}`"
        @click="emit('update:modelValue', modelValue.filter((_, i) => i !== index))"
      >
        <span class="min-w-0 break-all">{{ tag.name }}</span><X class="size-3 shrink-0" />
      </Button>
    </div>
    <div
      class="flex max-h-36 flex-wrap gap-1 overflow-y-auto rounded-lg border border-border p-2"
      role="group"
      aria-label="选择分组标签"
    >
      <Button
        v-for="tag in matching"
        :key="tag.id"
        variant="ghost"
        size="sm"
        class="h-auto max-w-full px-2 py-1 text-xs"
        :class="selected(tag) ? 'bg-muted text-foreground' : 'text-muted-foreground'"
        :aria-pressed="selected(tag)"
        :disabled="disabled || (!selected(tag) && modelValue.length >= 50)"
        @click="toggle(tag)"
      >
        <Check
          v-if="selected(tag)"
          class="size-3 shrink-0"
        /><span class="break-all">{{ tag.name }}</span>
      </Button>
      <p
        v-if="!matching.length"
        class="text-xs text-muted-foreground"
      >
        暂无匹配标签
      </p>
    </div>
    <Button
      v-if="canCreate"
      variant="outline"
      size="sm"
      class="h-auto justify-start whitespace-normal"
      :disabled="disabled || modelValue.length >= 50"
      @click="create"
    >
      <Plus class="shrink-0" /><span class="break-all">创建并选中「{{ name }}」</span>
    </Button>
    <p class="text-xs text-muted-foreground">
      名称最多 32 个字符；新标签与分组将在保存股票时生效。
    </p>
  </div>
</template>

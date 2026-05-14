<script setup lang="ts">
import Button from '@/components/common/Button.vue';
import Input from '@/components/common/Input.vue';
import Select from '@/components/common/Select.vue';
import SettingsHelpButton from '@/components/settings/SettingsHelpButton.vue';
import { cn } from '@/utils/cn';
import type { ConfigValidationIssue, SystemConfigFieldSchema, SystemConfigItem } from '@/types/systemConfig';
import { getFieldDescriptionZh, getFieldTitleZh } from '@/utils/systemConfigI18n';
import Badge from '@/components/common/Badge.vue';
import { ref, computed } from 'vue';

const props = withDefaults(
  defineProps<{
    item: SystemConfigItem;
    value: string;
    disabled?: boolean;
    issues?: ConfigValidationIssue[];
  }>(),
  { disabled: false, issues: () => [] },
);

const emit = defineEmits<{
  change: [key: string, value: string];
}>();

function normalizeSelectOptions(options: SystemConfigFieldSchema['options'] = []) {
  return options.map((option) => {
    if (typeof option === 'string') {
      return { value: option, label: option };
    }
    return option;
  });
}

function isMultiValueField(item: SystemConfigItem): boolean {
  const validation = (item.schema?.validation ?? {}) as Record<string, unknown>;
  return Boolean(validation.multiValue ?? validation.multi_value);
}

function parseMultiValues(value: string): string[] {
  if (!value) {
    return [''];
  }
  const values = value.split(',').map((entry) => entry.trim());
  return values.length ? values : [''];
}

function serializeMultiValues(values: string[]): string {
  return values.map((entry) => entry.trim()).join(',');
}

function inferPasswordIconType(key: string): 'password' | 'key' {
  return key.toUpperCase().includes('PASSWORD') ? 'password' : 'key';
}

const schema = computed(() => props.item.schema);
const isMultiValue = computed(() => isMultiValueField(props.item));
const title = computed(() => getFieldTitleZh(props.item.key, props.item.key));
const description = computed(() => getFieldDescriptionZh(props.item.key, schema.value?.description));
const hasError = computed(() => props.issues.some((issue) => issue.severity === 'error'));
const isPasswordEditable = ref(false);
const controlId = computed(() => `setting-${props.item.key}`);

const commonClass =
  'input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-4 text-sm transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';

function onPasswordFocus() {
  isPasswordEditable.value = true;
}

function emitChange(nextValue: string) {
  emit('change', props.item.key, nextValue);
}
</script>

<template>
  <div
    :class="
      cn(
        'rounded-[1.15rem] border bg-[var(--settings-surface)] p-4 shadow-soft-card transition-[background-color,border-color,box-shadow] duration-200',
        hasError ? 'border-danger/40 hover:border-danger/55' : 'border-[var(--settings-border)] hover:border-[var(--settings-border-strong)]',
        'hover:bg-[var(--settings-surface-hover)]',
      )
    "
  >
    <div class="mb-2 flex flex-wrap items-center gap-2">
      <label class="text-sm font-semibold text-foreground" :for="controlId">
        {{ title }}
      </label>
      <SettingsHelpButton
        :field-key="item.key"
        :title="title"
        :schema="schema"
        :description="description"
      />
      <Badge v-if="schema?.isSensitive" variant="history" size="sm">敏感</Badge>
      <Badge v-if="!schema?.isEditable" variant="default" size="sm">只读</Badge>
    </div>

    <p v-if="description" class="mb-3 max-w-full text-xs leading-5 text-muted-text">
      {{ description }}
    </p>

    <div>
      <textarea
        v-if="schema?.uiControl === 'textarea'"
        :id="controlId"
        :value="value"
        :disabled="disabled || !schema?.isEditable"
        :class="`${commonClass} min-h-[92px] resize-y py-3`"
        @input="emitChange(($event.target as HTMLTextAreaElement).value)"
      />

      <Select
        v-else-if="schema?.uiControl === 'select' && schema?.options?.length"
        :id="controlId"
        :model-value="value"
        :options="normalizeSelectOptions(schema.options)"
        :disabled="disabled || !schema.isEditable"
        placeholder="请选择"
        @update:model-value="emitChange"
      />

      <label
        v-else-if="schema?.uiControl === 'switch'"
        class="inline-flex cursor-pointer items-center gap-3"
      >
        <input
          :id="controlId"
          type="checkbox"
          :checked="value.trim().toLowerCase() === 'true'"
          :disabled="disabled || !schema?.isEditable"
          @change="emitChange(($event.target as HTMLInputElement).checked ? 'true' : 'false')"
        />
        <span class="text-sm text-secondary-text">
          {{ value.trim().toLowerCase() === 'true' ? '已启用' : '未启用' }}
        </span>
      </label>

      <div v-else-if="schema?.uiControl === 'password' && isMultiValue" class="space-y-2">
        <div
          v-for="(entry, index) in parseMultiValues(value)"
          :key="`${item.key}-${index}`"
          class="flex items-center gap-2"
        >
          <div class="flex-1">
            <Input
              type="password"
              allow-toggle-password
              :icon-type="inferPasswordIconType(item.key)"
              :id="index === 0 ? controlId : `${controlId}-${index}`"
              :readonly="!isPasswordEditable"
              :value="entry"
              :disabled="disabled || !schema?.isEditable"
              @focus="onPasswordFocus"
              @input="
                emitChange(
                  serializeMultiValues(
                    parseMultiValues(value).map((v, rowIndex) =>
                      rowIndex === index
                        ? ($event.target as HTMLInputElement).value
                        : v,
                    ),
                  ),
                )
              "
            />
          </div>
          <Button
            type="button"
            variant="settings-secondary"
            size="lg"
            class="px-3 text-xs text-muted-text shadow-none hover:text-danger"
            :disabled="disabled || !schema?.isEditable || parseMultiValues(value).length <= 1"
            @click="
              () => {
                const vals = parseMultiValues(value).filter((_, rowIndex) => rowIndex !== index);
                emitChange(serializeMultiValues(vals.length ? vals : ['']));
              }
            "
          >
            删除
          </Button>
        </div>
        <div class="flex items-center gap-2">
          <Button
            type="button"
            variant="settings-secondary"
            size="sm"
            class="text-xs shadow-none"
            :disabled="disabled || !schema?.isEditable"
            @click="emitChange(serializeMultiValues([...parseMultiValues(value), '']))"
          >
            添加 Key
          </Button>
        </div>
      </div>

      <Input
        v-else-if="schema?.uiControl === 'password'"
        type="password"
        allow-toggle-password
        :icon-type="inferPasswordIconType(item.key)"
        :id="controlId"
        :readonly="!isPasswordEditable"
        :value="value"
        :disabled="disabled || !schema?.isEditable"
        @focus="onPasswordFocus"
        @input="emitChange(($event.target as HTMLInputElement).value)"
      />

      <input
        v-else
        :id="controlId"
        :type="schema?.uiControl === 'number' ? 'number' : schema?.uiControl === 'time' ? 'time' : 'text'"
        :class="commonClass"
        :value="value"
        :disabled="disabled || !schema?.isEditable"
        @input="emitChange(($event.target as HTMLInputElement).value)"
      />
    </div>

    <p v-if="schema?.isSensitive" class="mt-3 text-[11px] leading-5 text-secondary-text">
      敏感内容默认隐藏，可点击眼睛图标查看明文。
      <template v-if="isMultiValue">支持添加多个输入框进行增删。</template>
    </p>

    <div v-if="issues.length" class="mt-2 space-y-1">
      <p
        v-for="(issue, index) in issues"
        :key="`${issue.code}-${issue.key}-${index}`"
        :class="issue.severity === 'error' ? 'text-xs text-danger' : 'text-xs text-warning'"
      >
        {{ issue.message }}
      </p>
    </div>
  </div>
</template>

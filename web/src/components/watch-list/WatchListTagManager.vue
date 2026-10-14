<script setup lang="ts">
import { ref } from 'vue';
import { Pencil, Trash2 } from 'lucide-vue-next';
import { watchListApi, type WatchListTag } from '@/api/watchList';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import AppConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import FieldInput from '@/components/forms/FieldInput.vue';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';

const props = defineProps<{ open: boolean; tags: WatchListTag[] }>();
const emit = defineEmits<{
  'update:open': [open: boolean]; created: [tag: WatchListTag]; renamed: [tag: WatchListTag]; deleted: [id: number];
}>();
const newName = ref('');
const editingId = ref<number | null>(null);
const editName = ref('');
const deleting = ref<WatchListTag | null>(null);
const busy = ref(false);
const error = ref<ParsedApiError | null>(null);
async function save(id?: number) {
  if (busy.value) return;
  busy.value = true;
  error.value = null;
  try {
    if (id !== undefined) {
      emit('renamed', await watchListApi.renameTag(id, editName.value.trim()));
      editingId.value = null;
    } else {
      emit('created', await watchListApi.createTag(newName.value.trim()));
      newName.value = '';
    }
  } catch (e) { error.value = getParsedApiError(e); }
  finally { busy.value = false; }
}
async function remove() {
  if (!deleting.value || busy.value) return;
  busy.value = true;
  error.value = null;
  try {
    await watchListApi.deleteTag(deleting.value.id);
    emit('deleted', deleting.value.id);
    deleting.value = null;
  } catch (e) { error.value = getParsedApiError(e); }
  finally { busy.value = false; }
}
</script>

<template>
  <Dialog
    :open="props.open"
    @update:open="!busy && emit('update:open', $event)"
  >
    <DialogContent class="max-w-md">
      <DialogHeader><DialogTitle>管理标签</DialogTitle><DialogDescription>标签在美股与 A 股之间共用，名称最多 32 个字符。</DialogDescription></DialogHeader>
      <ApiErrorAlert
        v-if="error"
        :error="error"
      />
      <div class="flex items-end gap-2">
        <FieldInput
          v-model="newName"
          label="新标签"
          placeholder="输入标签名称"
          class="min-w-0 flex-1"
          :disabled="busy"
          @keydown.enter.prevent="save()"
        />
        <Button
          :disabled="busy || !newName.trim()"
          @click="save()"
        >
          创建
        </Button>
      </div>
      <div
        class="max-h-[50dvh] space-y-2 overflow-y-auto"
        data-testid="tag-manager-list"
      >
        <p
          v-if="!tags.length"
          class="py-4 text-sm text-muted-foreground"
        >
          暂无标签
        </p>
        <div
          v-for="tag in tags"
          :key="tag.id"
          class="flex min-w-0 items-center gap-2 rounded-lg border border-border p-2"
        >
          <template v-if="editingId === tag.id">
            <FieldInput
              v-model="editName"
              :aria-label="`重命名 ${tag.name}`"
              class="min-w-0 flex-1"
              :disabled="busy"
              @keydown.enter.prevent="save(tag.id)"
            />
            <Button
              size="sm"
              :disabled="busy || !editName.trim()"
              @click="save(tag.id)"
            >
              保存
            </Button>
            <Button
              size="sm"
              variant="ghost"
              :disabled="busy"
              @click="editingId = null"
            >
              取消
            </Button>
          </template>
          <template v-else>
            <span class="min-w-0 flex-1 break-all text-sm">{{ tag.name }}</span>
            <Button
              size="icon-sm"
              variant="ghost"
              :aria-label="`重命名 ${tag.name}`"
              :disabled="busy"
              @click="editingId = tag.id; editName = tag.name"
            >
              <Pencil />
            </Button>
            <Button
              size="icon-sm"
              variant="ghost"
              :aria-label="`删除标签 ${tag.name}`"
              :disabled="busy"
              @click="deleting = tag"
            >
              <Trash2 />
            </Button>
          </template>
        </div>
      </div>
    </DialogContent>
  </Dialog>
  <AppConfirmDialog
    :open="deleting !== null"
    title="删除标签"
    :description="`确认删除「${deleting?.name ?? ''}」？会移除全部股票上的该标签，但不会删除股票。`"
    confirm-text="删除标签"
    destructive
    @update:open="!$event && !busy && (deleting = null)"
    @confirm="remove"
  />
</template>

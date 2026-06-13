<script setup lang="ts">
import Button from '@/components/common/Button.vue';
import Cropper from 'cropperjs';
import 'cropperjs/dist/cropper.css';
import { RotateCcw, ZoomIn, ZoomOut } from 'lucide-vue-next';
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';

const props = defineProps<{
  sourceUrl: string;
  isSubmitting?: boolean;
}>();

const emit = defineEmits<{
  cancel: [];
  cropped: [file: File];
  error: [message: string];
}>();

const imageRef = ref<HTMLImageElement | null>(null);
let cropper: Cropper | null = null;

function destroyCropper() {
  cropper?.destroy();
  cropper = null;
}

async function initCropper() {
  await nextTick();
  destroyCropper();
  if (!imageRef.value) return;
  cropper = new Cropper(imageRef.value, {
    aspectRatio: 1,
    viewMode: 1,
    autoCropArea: 0.9,
    background: false,
    responsive: true,
    dragMode: 'move',
  });
}

function emitCropped() {
  if (!cropper) return;
  const canvas = cropper.getCroppedCanvas({
    width: 512,
    height: 512,
    imageSmoothingEnabled: true,
    imageSmoothingQuality: 'high',
  });
  if (!canvas) {
    emit('error', '头像裁切失败');
    return;
  }
  canvas.toBlob(
    (blob) => {
      if (!blob) {
        emit('error', '头像裁切失败');
        return;
      }
      if (blob.size > 2 * 1024 * 1024) {
        emit('error', '头像不能超过 2MB');
        return;
      }
      emit('cropped', new File([blob], 'avatar.jpg', { type: 'image/jpeg' }));
    },
    'image/jpeg',
    0.9,
  );
}

onMounted(initCropper);
onBeforeUnmount(destroyCropper);
watch(() => props.sourceUrl, initCropper);
</script>

<template>
  <div class="space-y-4">
    <div class="overflow-hidden rounded-xl border border-border/70 bg-muted/30">
      <img ref="imageRef" :src="sourceUrl" alt="" class="block max-h-[360px] w-full object-contain" />
    </div>

    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center gap-2">
        <Button type="button" variant="secondary" size="sm" @click="cropper?.zoom(0.1)">
          <ZoomIn class="h-4 w-4" />
          放大
        </Button>
        <Button type="button" variant="secondary" size="sm" @click="cropper?.zoom(-0.1)">
          <ZoomOut class="h-4 w-4" />
          缩小
        </Button>
        <Button type="button" variant="secondary" size="sm" @click="cropper?.rotate(-90)">
          <RotateCcw class="h-4 w-4" />
          左转
        </Button>
      </div>
      <div class="flex items-center gap-2">
        <Button type="button" variant="ghost" size="sm" @click="emit('cancel')">取消</Button>
        <Button type="button" variant="primary" size="sm" :is-loading="isSubmitting" @click="emitCropped">
          使用头像
        </Button>
      </div>
    </div>
  </div>
</template>

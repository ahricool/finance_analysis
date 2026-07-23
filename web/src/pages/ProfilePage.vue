<script setup lang="ts">
import { authApi, type NotificationSettings, type UserGender, type UserProfileResponse } from '@/api/auth';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import Button from '@/components/common/Button.vue';
import Input from '@/components/common/Input.vue';
import SectionNavPanel from '@/components/common/SectionNavPanel.vue';
import SectionPageHeader from '@/components/common/SectionPageHeader.vue';
import AvatarCropper from '@/components/profile/AvatarCropper.vue';
import ChangePasswordCard from '@/components/settings/ChangePasswordCard.vue';
import SettingsAlert from '@/components/settings/SettingsAlert.vue';
import SettingsSectionCard from '@/components/settings/SettingsSectionCard.vue';
import { useAuthStore } from '@/stores/authStore';
import { Bell, Camera, LockKeyhole, Save, Upload, UserRound } from 'lucide-vue-next';
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';

type ProfileTab = 'info' | 'password' | 'notification';

const authStore = useAuthStore();
const activeTab = ref<ProfileTab>('info');
const profile = ref<UserProfileResponse | null>(null);
const isLoading = ref(false);
const pageError = ref<ParsedApiError | null>(null);
const infoError = ref<string | null>(null);
const infoSuccess = ref(false);
const notificationError = ref<string | null>(null);
const notificationSuccess = ref(false);
const avatarError = ref<string | null>(null);
const avatarSourceUrl = ref<string | null>(null);
const isSavingInfo = ref(false);
const isSavingNotification = ref(false);
const isUploadingAvatar = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

const infoForm = reactive({
  username: '',
  gender: 'unknown' as UserGender,
});

const notificationForm = reactive({
  ntfyUrl: '',
  telegramBotToken: '',
  telegramChatId: '',
});

const tabs: Array<{ key: ProfileTab; label: string; icon: typeof UserRound }> = [
  { key: 'info', label: '我的信息', icon: UserRound },
  { key: 'password', label: '更改密码', icon: LockKeyhole },
  { key: 'notification', label: '消息通知', icon: Bell },
];

const genderOptions: Array<{ value: UserGender; label: string }> = [
  { value: 'unknown', label: '未知' },
  { value: 'male', label: '男' },
  { value: 'female', label: '女' },
];

const avatarUrl = computed(() => profile.value?.avatarUrl || authStore.currentUser?.avatarUrl || '');

function firstNtfyUrl(notification: NotificationSettings): string {
  return notification.ntfy[0]?.url ?? '';
}

function firstTelegram(notification: NotificationSettings): { bot_token: string; chat_id: string } {
  return notification.telegram[0] ?? { bot_token: '', chat_id: '' };
}

function applyProfile(nextProfile: UserProfileResponse) {
  profile.value = nextProfile;
  infoForm.username = nextProfile.username;
  infoForm.gender = nextProfile.extra.gender;
  notificationForm.ntfyUrl = firstNtfyUrl(nextProfile.extra.notification);
  const telegram = firstTelegram(nextProfile.extra.notification);
  notificationForm.telegramBotToken = telegram.bot_token;
  notificationForm.telegramChatId = telegram.chat_id;
}

async function loadProfile() {
  isLoading.value = true;
  pageError.value = null;
  try {
    applyProfile(await authApi.getProfile());
  } catch (err) {
    pageError.value = getParsedApiError(err);
  } finally {
    isLoading.value = false;
  }
}

function clearAvatarSource() {
  if (avatarSourceUrl.value) {
    URL.revokeObjectURL(avatarSourceUrl.value);
    avatarSourceUrl.value = null;
  }
}

function chooseAvatar() {
  avatarError.value = null;
  fileInput.value?.click();
}

function onAvatarFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = '';
  if (!file) return;

  avatarError.value = null;
  if (!file.type.startsWith('image/')) {
    avatarError.value = '请选择图片文件';
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    avatarError.value = '头像不能超过 2MB';
    return;
  }

  clearAvatarSource();
  avatarSourceUrl.value = URL.createObjectURL(file);
}

async function uploadCroppedAvatar(file: File) {
  avatarError.value = null;
  isUploadingAvatar.value = true;
  try {
    await authApi.uploadAvatar(file);
    await authStore.refreshStatus();
    clearAvatarSource();
    await loadProfile();
  } catch (err) {
    avatarError.value = getParsedApiError(err).message;
  } finally {
    isUploadingAvatar.value = false;
  }
}

async function saveInfo() {
  infoError.value = null;
  infoSuccess.value = false;
  if (!infoForm.username.trim()) {
    infoError.value = '请输入昵称';
    return;
  }

  isSavingInfo.value = true;
  try {
    applyProfile(
      await authApi.updateProfile({
        username: infoForm.username.trim(),
        gender: infoForm.gender,
      }),
    );
    await authStore.refreshStatus();
    infoSuccess.value = true;
  } catch (err) {
    infoError.value = getParsedApiError(err).message;
  } finally {
    isSavingInfo.value = false;
  }
}

async function saveNotification() {
  notificationError.value = null;
  notificationSuccess.value = false;
  isSavingNotification.value = true;
  try {
    applyProfile(
      await authApi.updateProfile({
        notification: {
          ntfy: [{ url: notificationForm.ntfyUrl.trim() }],
          telegram: [
            {
              bot_token: notificationForm.telegramBotToken.trim(),
              chat_id: notificationForm.telegramChatId.trim(),
            },
          ],
        },
      }),
    );
    notificationSuccess.value = true;
  } catch (err) {
    notificationError.value = getParsedApiError(err).message;
  } finally {
    isSavingNotification.value = false;
  }
}

onMounted(() => {
  void loadProfile();
});
onBeforeUnmount(clearAvatarSource);
</script>

<template>
  <div class="space-y-5">
    <SectionPageHeader
      title="个人中心"
      description="管理账号资料、安全设置和通知渠道。"
    />

    <SettingsAlert
      v-if="pageError"
      title="加载失败"
      :message="pageError.message"
      variant="error"
    />

    <div class="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
      <SectionNavPanel
        :items="tabs"
        :active-key="activeTab"
        @select="activeTab = $event as ProfileTab"
      />

      <section class="min-w-0">
        <SettingsSectionCard
          v-if="activeTab === 'info'"
          title="我的信息"
        >
          <div v-if="isLoading" class="py-10 text-center text-sm text-muted-text">加载中...</div>
          <div v-else class="space-y-5">
            <div class="flex flex-col gap-4 sm:flex-row sm:items-center">
              <div
                class="flex h-24 w-24 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border/70 bg-primary/10 text-primary"
              >
                <img v-if="avatarUrl" :src="avatarUrl" alt="" class="h-full w-full object-cover" />
                <Camera v-else class="h-8 w-8" />
              </div>
              <div class="min-w-0 flex-1 space-y-3">
                <input
                  ref="fileInput"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  class="hidden"
                  @change="onAvatarFileChange"
                />
                <Button type="button" variant="secondary" size="sm" @click="chooseAvatar">
                  <Upload class="h-4 w-4" />
                  上传头像
                </Button>
                <SettingsAlert
                  v-if="avatarError"
                  title="头像保存失败"
                  :message="avatarError"
                  variant="error"
                />
              </div>
            </div>

            <AvatarCropper
              v-if="avatarSourceUrl"
              :source-url="avatarSourceUrl"
              :is-submitting="isUploadingAvatar"
              @cancel="clearAvatarSource"
              @error="avatarError = $event"
              @cropped="uploadCroppedAvatar"
            />

            <form class="space-y-4" @submit.prevent="saveInfo">
              <Input
                id="profile-email"
                label="邮箱"
                class="max-w-sm"
                :value="profile?.email ?? ''"
                disabled
                autocomplete="email"
              />
              <Input
                id="profile-username"
                label="昵称"
                class="max-w-xs"
                placeholder="输入昵称"
                :value="infoForm.username"
                :disabled="isSavingInfo"
                autocomplete="nickname"
                @input="infoForm.username = ($event.target as HTMLInputElement).value"
              />
              <fieldset class="max-w-xs">
                <legend class="mb-2 text-sm font-medium text-foreground">
                  性别
                </legend>
                <div class="flex flex-wrap gap-2">
                  <label
                    v-for="option in genderOptions"
                    :key="option.value"
                    :class="[
                      'inline-flex h-10 cursor-pointer items-center gap-2 rounded-xl border px-3 text-sm transition-colors',
                      infoForm.gender === option.value
                        ? 'border-primary/45 bg-primary/10 text-primary'
                        : 'border-border/70 bg-card/60 text-secondary-text hover:border-primary/30 hover:text-foreground',
                      isSavingInfo ? 'cursor-not-allowed opacity-60' : '',
                    ]"
                  >
                    <input
                      :id="`profile-gender-${option.value}`"
                      type="radio"
                      name="profile-gender"
                      class="h-4 w-4 accent-primary"
                      :value="option.value"
                      :checked="infoForm.gender === option.value"
                      :disabled="isSavingInfo"
                      @change="infoForm.gender = option.value"
                    />
                    <span>{{ option.label }}</span>
                  </label>
                </div>
              </fieldset>

              <div>
                <Button type="submit" variant="primary" :is-loading="isSavingInfo">
                  <Save class="h-4 w-4" />
                  保存信息
                </Button>
              </div>
            </form>

            <SettingsAlert
              v-if="infoError"
              title="保存失败"
              :message="infoError"
              variant="error"
            />
            <SettingsAlert
              v-if="infoSuccess"
              title="保存成功"
              message="个人信息已更新。"
              variant="success"
            />
          </div>
        </SettingsSectionCard>

        <ChangePasswordCard v-else-if="activeTab === 'password'" />

        <SettingsSectionCard
          v-else
          title="消息通知"
        >
          <form class="space-y-5" @submit.prevent="saveNotification">
            <div class="space-y-4">
              <Input
                id="profile-ntfy-url"
                label="ntfy URL"
                class="max-w-lg"
                placeholder="https://ntfy.sh/topic"
                :value="notificationForm.ntfyUrl"
                :disabled="isSavingNotification"
                @input="notificationForm.ntfyUrl = ($event.target as HTMLInputElement).value"
              />
              <Input
                id="profile-telegram-chat"
                label="Telegram Chat ID"
                class="max-w-sm"
                placeholder="chat_id"
                :value="notificationForm.telegramChatId"
                :disabled="isSavingNotification"
                @input="notificationForm.telegramChatId = ($event.target as HTMLInputElement).value"
              />
            </div>
            <Input
              id="profile-telegram-token"
              type="password"
              allow-toggle-password
              icon-type="key"
              label="Telegram Bot Token"
              class="max-w-2xl"
              placeholder="bot_token"
              :value="notificationForm.telegramBotToken"
              :disabled="isSavingNotification"
              autocomplete="off"
              @input="notificationForm.telegramBotToken = ($event.target as HTMLInputElement).value"
            />

            <Button type="submit" variant="primary" :is-loading="isSavingNotification">
              <Save class="h-4 w-4" />
              保存通知
            </Button>

            <SettingsAlert
              v-if="notificationError"
              title="保存失败"
              :message="notificationError"
              variant="error"
            />
            <SettingsAlert
              v-if="notificationSuccess"
              title="保存成功"
              message="通知配置已保存。"
              variant="success"
            />
          </form>
        </SettingsSectionCard>
      </section>
    </div>
  </div>
</template>

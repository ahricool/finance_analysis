<script setup lang="ts">
import { agentApi } from '@/api/agent';
import type { SkillInfo } from '@/api/agent';
import { getParsedApiError } from '@/api/error';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import LoadingButton from '@/components/app/LoadingButton.vue';
import ConfirmDialog from '@/components/app/AppConfirmDialog.vue';
import ChatScrollArea from '@/components/chat/ChatScrollArea.vue';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import DashboardStateBlock from '@/components/dashboard/DashboardStateBlock.vue';
import { cn } from '@/utils/cn';
import { formatDate } from '@/utils/format';
import { downloadSession, formatSessionAsMarkdown } from '@/utils/chatExport';
import {
  buildFollowUpPrompt,
  parseFollowUpRecordId,
  resolveChatFollowUpContext,
  sanitizeFollowUpStockCode,
  sanitizeFollowUpStockName,
} from '@/utils/chatFollowUp';
import type { ChatFollowUpContext } from '@/utils/chatFollowUp';
import { isNearBottom } from '@/utils/chatScroll';
import { getReportText } from '@/utils/reportLanguage';
import { renderMarkdownToHtml } from '@/utils/renderMarkdown';
import { useAgentChatStore, type Message, type ProgressStep } from '@/stores/agentChatStore';
import { computed, nextTick, onMounted, onUnmounted, ref, unref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { ArrowDown, ChevronRight, Download, History, Lightbulb, Menu, Plus, Send, Trash2, Zap } from 'lucide-vue-next';

const QUICK_QUESTIONS = [
  { label: '用缠论分析茅台', skill: 'chan_theory' },
  { label: '波浪理论看宁德时代', skill: 'wave_theory' },
  { label: '分析比亚迪趋势', skill: 'bull_trend' },
  { label: '箱体震荡技能看中芯国际', skill: 'box_oscillation' },
  { label: '分析腾讯 hk00700', skill: 'bull_trend' },
  { label: '用情绪周期分析东方财富', skill: 'emotion_cycle' },
];

const MAX_SELECTED_SKILLS = 3;

function getMessageSkillNames(msg: Message): string[] {
  if (msg.skillNames?.length) return msg.skillNames;
  if (msg.skillName) return [msg.skillName];
  if (msg.skills?.length) return msg.skills;
  if (msg.skill) return [msg.skill];
  return [];
}

function getMessageSkillLabel(msg: Message): string {
  return getMessageSkillNames(msg).join('、');
}

function renderMd(content: string): string {
  return renderMarkdownToHtml(content);
}

const route = useRoute();
const router = useRouter();
const text = getReportText('zh');

const input = ref('');
const skills = ref<SkillInfo[]>([]);
const selectedSkillIds = ref<string[]>([]);
const showSkillDesc = ref<string | null>(null);
const expandedThinking = ref<Set<string>>(new Set());
const deleteConfirmId = ref<string | null>(null);
const sidebarOpen = ref(false);
const sending = ref(false);
const isFollowUpContextLoading = ref(false);
const sendToast = ref<{ type: 'success' | 'error'; message: string } | null>(null);
const copiedMessages = ref<Set<string>>(new Set());
const showJumpToBottom = ref(false);
const copyResetTimerRef: Partial<Record<string, number>> = {};
const messagesViewportRef = ref<HTMLElement | null>(null);
const messagesEndRef = ref<HTMLElement | null>(null);
const isMountedRef = ref(true);
let sendToastTimer: number | null = null;
let followUpHydrationToken = 0;
const followUpContextRef = ref<ChatFollowUpContext | null>(null);
const shouldStickToBottomRef = ref(true);
type ChatScrollBehavior = 'auto' | 'instant' | 'smooth';
let pendingScrollBehavior: ChatScrollBehavior = 'auto';

const scrollAreaRef = ref<InstanceType<typeof ChatScrollArea> | null>(null);

watch(
  () => scrollAreaRef.value,
  (inst) => {
    const inner = inst?.viewportEl;
    messagesViewportRef.value = inner ? unref(inner) : null;
  },
  { flush: 'post' },
);

const chat = useAgentChatStore((s) => ({
  messages: s.messages,
  loading: s.loading,
  progressSteps: s.progressSteps,
  sessionId: s.sessionId,
  sessions: s.sessions,
  sessionsLoading: s.sessionsLoading,
  chatError: s.chatError,
  loadSessions: s.loadSessions,
  loadInitialSession: s.loadInitialSession,
  switchSession: s.switchSession,
  startStream: s.startStream,
  clearCompletionBadge: s.clearCompletionBadge,
}));

const messages = computed(() => unref(chat.messages));
const loading = computed(() => unref(chat.loading));
const progressSteps = computed(() => unref(chat.progressSteps));
const sessionId = computed(() => unref(chat.sessionId));
const sessions = computed(() => unref(chat.sessions));
const sessionsLoading = computed(() => unref(chat.sessionsLoading));
const chatError = computed(() => unref(chat.chatError));

onMounted(() => {
  isMountedRef.value = true;
  unref(chat.loadInitialSession)();
  unref(chat.clearCompletionBadge)();
  agentApi
    .getSkills()
    .then((res) => {
      skills.value = res.skills;
      const defaultId = res.default_skill_id || res.skills[0]?.id || '';
      selectedSkillIds.value = defaultId ? [defaultId] : [];
    })
    .catch((err) => {
      console.error('Failed to load chat skills:', err);
    });
});

onUnmounted(() => {
  isMountedRef.value = false;
  if (sendToastTimer !== null) {
    window.clearTimeout(sendToastTimer);
  }
  Object.values(copyResetTimerRef).forEach((timerId) => {
    if (timerId !== undefined) {
      window.clearTimeout(timerId);
    }
  });
});

const availableSkillIds = computed(() => new Set(skills.value.map((s) => s.id)));
const quickQuestions = computed(() =>
  QUICK_QUESTIONS.filter(
    (question) => availableSkillIds.value.size === 0 || availableSkillIds.value.has(question.skill),
  ),
);
const selectedSkillIdSet = computed(() => new Set(selectedSkillIds.value));
const skillLimitReached = computed(() => selectedSkillIds.value.length >= MAX_SELECTED_SKILLS);

function getSkillNames(skillIds: string[]): string[] {
  return skillIds.map((id) => skills.value.find((s) => s.id === id)?.name || id);
}

function normalizeSelectedSkillIds(skillIds: string[]): string[] {
  const normalized: string[] = [];
  for (const skillId of skillIds) {
    const cleaned = skillId.trim();
    if (cleaned && !normalized.includes(cleaned)) {
      normalized.push(cleaned);
    }
  }
  return normalized.slice(0, MAX_SELECTED_SKILLS);
}

function toggleSkillSelection(skillId: string) {
  if (selectedSkillIds.value.includes(skillId)) {
    selectedSkillIds.value = selectedSkillIds.value.filter((id) => id !== skillId);
    return;
  }
  if (selectedSkillIds.value.length >= MAX_SELECTED_SKILLS) {
    return;
  }
  selectedSkillIds.value = [...selectedSkillIds.value, skillId];
}

function scrollToBottom(behavior: ChatScrollBehavior = 'auto') {
  messagesEndRef.value?.scrollIntoView({ behavior });
}

function requestScrollToBottom(behavior: ChatScrollBehavior = 'auto') {
  shouldStickToBottomRef.value = true;
  pendingScrollBehavior = behavior;
  showJumpToBottom.value = false;
}

function syncScrollState() {
  const viewport = messagesViewportRef.value;
  if (!viewport) return;
  const nearBottom = isNearBottom({
    scrollTop: viewport.scrollTop,
    clientHeight: viewport.clientHeight,
    scrollHeight: viewport.scrollHeight,
  });
  shouldStickToBottomRef.value = nearBottom;
  if (nearBottom) {
    showJumpToBottom.value = false;
  }
}

function handleMessagesScroll() {
  syncScrollState();
}

watch(sessionId, () => {
  nextTick(() => syncScrollState());
});

watch(
  [messages, progressSteps, loading, sessionId],
  () => {
    const behavior = pendingScrollBehavior;
    const shouldAutoScroll = shouldStickToBottomRef.value;
    if (!shouldAutoScroll) {
      if (messages.value.length > 0 || progressSteps.value.length > 0 || loading.value) {
        showJumpToBottom.value = true;
      }
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      scrollToBottom(behavior);
      pendingScrollBehavior = loading.value ? 'auto' : 'smooth';
    });
    return () => window.cancelAnimationFrame(frame);
  },
  { deep: true },
);

watch(loading, (ld) => {
  if (!ld) {
    pendingScrollBehavior = 'smooth';
  }
});

function handleStartNewChat() {
  followUpContextRef.value = null;
  requestScrollToBottom('auto');
  useAgentChatStore.getState().startNewChat();
  sidebarOpen.value = false;
}

async function handleSwitchSession(targetSessionId: string) {
  requestScrollToBottom('auto');
  await unref(chat.switchSession)(targetSessionId);
  sidebarOpen.value = false;
}

function confirmDelete() {
  const id = deleteConfirmId.value;
  if (!id) return;
  agentApi
    .deleteChatSession(id)
    .then(() => {
      unref(chat.loadSessions)();
      if (id === sessionId.value) {
        handleStartNewChat();
      }
    })
    .catch((err) => {
      console.error('Failed to delete chat session:', err);
    });
  deleteConfirmId.value = null;
}

function applyFollowUpFromRoute() {
  const stock = sanitizeFollowUpStockCode((route.query.stock as string) || null);
  const name = sanitizeFollowUpStockName((route.query.name as string) || null);
  const recordId = parseFollowUpRecordId((route.query.recordId as string) || null);

  if (!stock) {
    void router.replace({ query: {} });
    return;
  }

  const hydrationToken = ++followUpHydrationToken;
  input.value = buildFollowUpPrompt(stock, name);
  followUpContextRef.value = {
    stock_code: stock,
    stock_name: name,
  };
  if (recordId !== undefined) {
    isFollowUpContextLoading.value = true;
  }
  void resolveChatFollowUpContext({
    stockCode: stock,
    stockName: name,
    recordId,
  })
    .then((context) => {
      if (!isMountedRef.value || followUpHydrationToken !== hydrationToken) {
        return;
      }
      followUpContextRef.value = context;
    })
    .finally(() => {
      if (isMountedRef.value && followUpHydrationToken === hydrationToken) {
        isFollowUpContextLoading.value = false;
      }
    });
  void router.replace({ query: {} });
}

watch(
  () => route.query,
  () => {
    if (route.query.stock) {
      applyFollowUpFromRoute();
    }
  },
  { immediate: true },
);

async function handleSend(overrideMessage?: string, overrideSkillIds?: string[]) {
  const msgText = (overrideMessage ?? input.value).trim();
  if (!msgText || loading.value) return;
  const usedSkillIds = normalizeSelectedSkillIds(overrideSkillIds ?? selectedSkillIds.value);
  const usedSkillNames = usedSkillIds.length > 0 ? getSkillNames(usedSkillIds) : ['通用'];

  const payload = {
    message: msgText,
    session_id: sessionId.value,
    ...(usedSkillIds.length > 0 ? { skills: usedSkillIds } : {}),
    context: followUpContextRef.value ?? undefined,
  };
  followUpHydrationToken += 1;
  followUpContextRef.value = null;
  isFollowUpContextLoading.value = false;

  input.value = '';
  requestScrollToBottom('smooth');
  await unref(chat.startStream)(payload, {
    skillNames: usedSkillNames,
    skillName: usedSkillNames.join('、'),
  });
}

function handleKeyDown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    void handleSend();
  }
}

function handleQuickQuestion(q: (typeof QUICK_QUESTIONS)[0]) {
  selectedSkillIds.value = [q.skill];
  void handleSend(q.label, [q.skill]);
}

function showSendFeedback(
  nextToast: { type: 'success' | 'error'; message: string },
  durationMs: number,
) {
  if (sendToastTimer !== null) {
    window.clearTimeout(sendToastTimer);
  }
  sendToast.value = nextToast;
  sendToastTimer = window.setTimeout(() => {
    sendToast.value = null;
    sendToastTimer = null;
  }, durationMs);
}

async function sendChatToNotify() {
  if (sending.value) return;
  sending.value = true;
  sendToast.value = null;
  try {
    const content = formatSessionAsMarkdown(messages.value);
    await agentApi.sendChat(content);
    showSendFeedback({ type: 'success', message: '已发送到通知渠道' }, 3000);
  } catch (err) {
    const parsed = getParsedApiError(err);
    showSendFeedback({ type: 'error', message: parsed.message || '发送失败' }, 5000);
  } finally {
    sending.value = false;
  }
}

function toggleThinking(msgId: string) {
  const next = new Set(expandedThinking.value);
  if (next.has(msgId)) next.delete(msgId);
  else next.add(msgId);
  expandedThinking.value = next;
}

async function copyMessageToClipboard(msgId: string, content: string) {
  try {
    await navigator.clipboard.writeText(content);
    copiedMessages.value = new Set([...copiedMessages.value, msgId]);
    const existingTimer = copyResetTimerRef[msgId];
    if (existingTimer !== undefined) {
      window.clearTimeout(existingTimer);
    }
    copyResetTimerRef[msgId] = window.setTimeout(() => {
      const s = new Set(copiedMessages.value);
      s.delete(msgId);
      copiedMessages.value = s;
      delete copyResetTimerRef[msgId];
    }, 2000);
  } catch (err) {
    console.error('Copy failed:', err);
  }
}

function downloadMessageAsMarkdown(msg: Message) {
  const skillLabel = getMessageSkillLabel(msg);
  const heading =
    msg.role === 'user' ? '# 用户消息' : `# AI 回复${skillLabel ? ` · ${skillLabel}` : ''}`;
  const body = [heading, '', msg.content].join('\n');
  const blob = new Blob([body], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${msg.role === 'user' ? 'user' : 'assistant'}-message-${msg.id}.md`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function getCurrentStage(steps: ProgressStep[]): string {
  if (steps.length === 0) return '正在连接...';
  const last = steps[steps.length - 1];
  if (last.type === 'thinking') return last.message || 'AI 正在思考...';
  if (last.type === 'tool_start') return `${last.display_name || last.tool}...`;
  if (last.type === 'tool_done') return `${last.display_name || last.tool} 完成`;
  if (last.type === 'generating') return last.message || '正在生成最终分析...';
  return '处理中...';
}

function progressStepText(step: ProgressStep): string {
  if (step.type === 'thinking') {
    return step.message || `第 ${step.step} 步：思考`;
  }
  if (step.type === 'tool_start') {
    return `${step.display_name || step.tool}...`;
  }
  if (step.type === 'tool_done') {
    return `${step.display_name || step.tool} (${step.duration}s)`;
  }
  if (step.type === 'generating') {
    return step.message || '生成分析';
  }
  return '';
}

function progressStepClasses(step: ProgressStep): { row: string; dot: string } {
  if (step.type === 'thinking') {
    return { row: 'text-muted-foreground', dot: 'bg-primary' };
  }
  if (step.type === 'tool_start') {
    return { row: 'text-muted-foreground', dot: 'bg-primary' };
  }
  if (step.type === 'tool_done') {
    return {
      row: step.success ? 'text-success' : 'text-destructive',
      dot: step.success ? 'bg-success' : 'bg-destructive',
    };
  }
  if (step.type === 'generating') {
    return { row: 'text-muted-foreground', dot: 'bg-primary' };
  }
  return { row: 'text-muted-foreground', dot: 'bg-muted-foreground' };
}

function thinkingSummary(msg: Message): string {
  const toolSteps = (msg.thinkingSteps || []).filter((s) => s.type === 'tool_done');
  const totalDuration = toolSteps.reduce((sum, s) => sum + (s.duration || 0), 0);
  return `${toolSteps.length} 个工具调用 · ${totalDuration.toFixed(1)}s`;
}

function onTextareaInput(e: Event) {
  const t = e.target as HTMLTextAreaElement;
  t.style.height = 'auto';
  t.style.height = `${Math.min(t.scrollHeight, 200)}px`;
}
</script>

<template>
  <!-- eslint-disable vue/no-v-html -->
  <!-- v-html values in this template come from DOMPurify-backed Markdown renderers. -->
  <div
    data-testid="conversation-workspace"
    class="flex h-[calc(100dvh-3.5rem-env(safe-area-inset-top)-env(safe-area-inset-bottom))] w-full min-w-0 gap-4 overflow-hidden py-4"
  >
    <div
      class="hidden w-[clamp(18rem,22vw,22rem)] flex-shrink-0 self-start flex-col overflow-hidden rounded-[1.25rem] border border-border bg-card/82 shadow-sm md:flex"
    >
      <div class="flex items-center justify-between border-b border-border bg-muted/20 p-3.5">
        <h2
          class="text-sm font-semibold text-primary uppercase tracking-[0.2em] flex items-center gap-2"
        >
          <History class="size-5" />
          历史对话
        </h2>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="开启新对话"
          @click="handleStartNewChat"
        >
          <Plus class="size-4" />
        </Button>
      </div>
      <ScrollArea
        class="max-h-[calc(100vh-10rem)] flex-none"
        data-testid="conversation-list-scroll"
      >
        <div class="p-3">
          <DashboardStateBlock
            v-if="sessionsLoading"
            loading
            compact
            title="加载对话中..."
            class="rounded-2xl border border-dashed border-border/50 bg-muted/30"
          />
          <DashboardStateBlock
            v-else-if="sessions.length === 0"
            compact
            title="暂无历史对话"
            description="开始提问后，这里会保留会话记录。"
            class="rounded-2xl border border-dashed border-border/50 bg-muted/30"
          />
          <div
            v-else
            class="space-y-2"
          >
            <div
              v-for="s in sessions"
              :key="s.session_id"
              class="flex items-start gap-1"
            >
              <button
                type="button"
                :class="
                  cn(
                    'flex min-h-12 min-w-0 flex-1 items-start gap-2 rounded-lg border border-transparent p-2 text-left transition-colors hover:bg-muted',
                    s.session_id === sessionId && 'border-primary/25 bg-primary/10',
                  )
                "
                :aria-label="`切换到对话 ${s.title}`"
                :aria-current="s.session_id === sessionId ? 'page' : undefined"
                @click="handleSwitchSession(s.session_id)"
              >
                <div
                  :class="
                    cn(
                      'h-10 w-1 shrink-0 rounded-full bg-border',
                      s.session_id === sessionId && 'bg-primary',
                    )
                  "
                />
                <div class="min-w-0 flex-1">
                  <span class="block truncate text-sm font-medium">{{ s.title }}</span>
                  <div class="mt-0.5 flex items-center gap-2">
                    <span class="text-xs text-muted-foreground">{{ s.message_count }} 条对话</span>
                    <template v-if="s.last_active">
                      <span class="inline-block size-1 rounded-full bg-border" />
                      <span class="text-xs text-muted-foreground">
                        {{ formatDate(s.last_active) }}
                      </span>
                    </template>
                  </div>
                </div>
              </button>
              <Button
                variant="ghost"
                size="icon"
                class="shrink-0 text-muted-foreground hover:text-destructive"
                :aria-label="`删除对话 ${s.title}`"
                @click="deleteConfirmId = s.session_id"
              >
                <Trash2 class="size-4" />
              </Button>
            </div>
          </div>
        </div>
      </ScrollArea>
    </div>

    <Sheet
      :open="sidebarOpen"
      @update:open="sidebarOpen = $event"
    >
      <SheetContent
        side="left"
        class="flex max-h-dvh w-[min(22rem,90vw)] flex-col overflow-hidden"
      >
        <SheetHeader class="text-left">
          <SheetTitle class="flex items-center gap-2">
            <History class="size-5 text-primary" />历史对话
          </SheetTitle>
          <SheetDescription>切换历史会话，或开启一段新的问股对话。</SheetDescription>
        </SheetHeader>
        <Separator />
        <Button
          variant="outline"
          class="mx-4"
          @click="handleStartNewChat"
        >
          <Plus class="size-4" />开启新对话
        </Button>
        <ScrollArea
          class="min-h-0 flex-1"
          data-testid="conversation-list-scroll-mobile"
        >
          <div class="p-3">
            <DashboardStateBlock
              v-if="sessionsLoading"
              loading
              compact
              title="加载对话中..."
              class="rounded-2xl border border-dashed border-border/50 bg-muted/30"
            />
            <div
              v-else
              class="space-y-2"
            >
              <div
                v-for="s in sessions"
                :key="`m-${s.session_id}`"
                class="flex items-start gap-1"
              >
                <button
                  type="button"
                  :class="
                    cn(
                      'flex min-h-12 min-w-0 flex-1 items-start gap-2 rounded-lg border border-transparent p-2 text-left transition-colors hover:bg-muted',
                      s.session_id === sessionId && 'border-primary/25 bg-primary/10',
                    )
                  "
                  @click="handleSwitchSession(s.session_id)"
                >
                  <div
                    :class="
                      cn(
                        'h-10 w-1 shrink-0 rounded-full bg-border',
                        s.session_id === sessionId && 'bg-primary',
                      )
                    "
                  />
                  <div class="min-w-0 flex-1">
                    <span class="block truncate text-sm font-medium">{{ s.title }}</span>
                  </div>
                </button>
              </div>
            </div>
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>

    <ConfirmDialog
      :open="Boolean(deleteConfirmId)"
      title="删除对话"
      description="删除后，该对话将不可恢复，确认删除吗？"
      confirm-text="删除"
      cancel-text="取消"
      destructive
      @confirm="confirmDelete"
      @update:open="deleteConfirmId = null"
    />

    <div class="flex h-full min-w-0 flex-1 flex-col overflow-hidden">
      <header class="mb-4 flex-shrink-0 space-y-3">
        <div class="flex items-start justify-between gap-4">
          <h1 class="text-2xl font-bold text-foreground flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon-sm"
              class="-ml-1 md:hidden"
              aria-label="历史对话"
              @click="sidebarOpen = true"
            >
              <Menu class="size-5" />
            </Button>
            <Lightbulb class="size-6 text-primary" />
            问股
          </h1>
          <div
            v-if="messages.length > 0"
            class="flex flex-shrink-0 flex-wrap items-center justify-end gap-2"
          >
            <TooltipProvider :delay-duration="0">
              <Tooltip>
                <TooltipTrigger as-child>
                  <Button
                    variant="default"
                    size="sm"
                    aria-label="导出会话为 Markdown 文件"
                    @click="downloadSession(messages)"
                  >
                    <Download class="size-4" />
                    导出会话
                  </Button>
                </TooltipTrigger>
                <TooltipContent>导出会话为 Markdown 文件</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger as-child>
                  <LoadingButton
                    variant="default"
                    size="sm"
                    :loading="sending"
                    loading-text="发送中"
                    aria-label="发送到已配置的通知机器人/邮箱"
                    @click="sendChatToNotify"
                  >
                    <Send class="size-4" />
                    发送
                  </LoadingButton>
                </TooltipTrigger>
                <TooltipContent>发送到已配置的通知机器人/邮箱</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>
        <p class="text-muted-foreground text-sm">
          向 AI 询问个股分析，获取基于技能视角的交易建议与实时决策报告。
        </p>
        <Alert
          v-if="sendToast"
          :variant="sendToast.type === 'error' ? 'destructive' : 'default'"
          class="max-w-md rounded-xl px-3 py-2 text-xs shadow-none"
        >
          <AlertTitle>{{ sendToast.type === 'success' ? '发送成功' : '发送失败' }}</AlertTitle>
          <AlertDescription>{{ sendToast.message }}</AlertDescription>
        </Alert>
      </header>

      <div
        class="relative z-10 flex min-h-0 flex-1 flex-col overflow-hidden border border-border bg-card/78 rounded-xl border bg-card text-card-foreground shadow-sm"
      >
        <ChatScrollArea
          ref="scrollAreaRef"
          class="relative z-10 flex-1"
          viewport-class-name="space-y-6 p-4 md:p-6"
          test-id="conversation-message-scroll"
          @scroll="handleMessagesScroll"
        >
          <div
            v-if="messages.length === 0 && !loading"
            class="flex h-full items-center justify-center"
          >
            <Empty class="max-w-2xl border-dashed bg-card/55">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <Lightbulb class="size-6" />
                </EmptyMedia>
                <EmptyTitle>开始问股</EmptyTitle>
                <EmptyDescription>
                  输入「分析 600519」或「茅台现在能买吗」，AI 将调用实时数据工具为您生成决策报告。
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <div class="flex max-w-lg flex-wrap justify-center gap-2">
                  <Button
                    v-for="(q, i) in quickQuestions"
                    :key="i"
                    variant="outline"
                    size="sm"
                    @click="handleQuickQuestion(q)"
                  >
                    {{ q.label }}
                  </Button>
                </div>
              </EmptyContent>
            </Empty>
          </div>

          <template v-else>
            <div
              v-for="msg in messages"
              :key="msg.id"
              :class="['flex gap-4', msg.role === 'user' ? 'flex-row-reverse' : '']"
            >
              <div
                :class="
                  cn(
                    'flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[10px] font-bold shadow-sm transition-all',
                    msg.role === 'user'
                      ? 'flex size-8 shrink-0 items-center justify-center rounded-full bg-secondary text-secondary-foreground'
                      : 'flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary',
                  )
                "
              >
                {{ msg.role === 'user' ? 'U' : 'AI' }}
              </div>
              <div
                :class="
                  cn(
                    'group/message min-w-0 w-fit max-w-[min(100%,48rem)] overflow-hidden px-5 py-3.5 transition-colors',
                    msg.role === 'user'
                      ? 'rounded-2xl border border-primary/20 bg-primary/10 px-4 py-3 text-sm'
                      : 'rounded-2xl border bg-card px-4 py-3 text-sm',
                  )
                "
              >
                <template v-if="msg.role === 'assistant'">
                  <div
                    v-if="getMessageSkillLabel(msg)"
                    class="mb-2"
                  >
                    <Badge
                      variant="secondary"
                      :aria-label="`技能 ${getMessageSkillLabel(msg)}`"
                    >
                      <Zap class="size-3" />
                      {{ getMessageSkillLabel(msg) }}
                    </Badge>
                  </div>

                  <button
                    v-if="msg.thinkingSteps && msg.thinkingSteps.length > 0"
                    type="button"
                    class="flex items-center gap-2 text-xs text-muted-foreground hover:text-muted-foreground transition-colors mb-2 w-full text-left"
                    @click="toggleThinking(msg.id)"
                  >
                    <ChevronRight
                      :class="[
                        'w-3 h-3 transition-transform flex-shrink-0',
                        expandedThinking.has(msg.id) ? 'rotate-90' : '',
                      ]"
                    />
                    <span class="flex items-center gap-1.5">
                      <span class="opacity-60">思考过程</span>
                      <span class="text-muted-foreground/50">·</span>
                      <span class="opacity-50">{{ thinkingSummary(msg) }}</span>
                    </span>
                  </button>

                  <div
                    v-if="expandedThinking.has(msg.id) && msg.thinkingSteps"
                    class="mb-3 pl-5 border-l border-border/40 space-y-1.5 animate-fade-in"
                  >
                    <div
                      v-for="(step, idx) in msg.thinkingSteps"
                      :key="idx"
                      :class="
                        cn(
                          'flex items-start gap-2 text-xs text-muted-foreground',
                          progressStepClasses(step).row,
                        )
                      "
                    >
                      <span
                        :class="
                          cn(
                            'mt-1 size-2 shrink-0 rounded-full bg-muted-foreground',
                            progressStepClasses(step).dot,
                          )
                        "
                      />
                      <span class="leading-relaxed">{{ progressStepText(step) }}</span>
                    </div>
                  </div>

                  <div class="relative">
                    <div class="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        class="inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 text-xs text-muted-foreground hover:bg-muted"
                        :aria-label="copiedMessages.has(msg.id) ? text.copied : text.copy"
                        @click="copyMessageToClipboard(msg.id, msg.content)"
                      >
                        {{ copiedMessages.has(msg.id) ? text.copied : text.copy }}
                      </button>
                      <button
                        type="button"
                        class="inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 text-xs text-muted-foreground hover:bg-muted"
                        aria-label="导出此条消息为 Markdown"
                        @click="downloadMessageAsMarkdown(msg)"
                      >
                        导出
                      </button>
                    </div>
                    <div
                      class="prose pr-20 sm:pr-24"
                      v-html="renderMd(msg.content)"
                    />
                  </div>
                </template>
                <template v-else>
                  <p
                    v-for="(line, i) in msg.content.split('\n')"
                    :key="i"
                    class="mb-1 last:mb-0 leading-relaxed"
                  >
                    {{ line || '\u00A0' }}
                  </p>
                </template>
              </div>
            </div>
          </template>

          <div
            v-if="loading"
            class="flex gap-4"
          >
            <div
              class="w-8 h-8 rounded-full bg-card text-foreground flex items-center justify-center flex-shrink-0 text-xs font-bold"
            >
              AI
            </div>
            <div
              class="min-w-[200px] max-w-[min(100%,48rem)] overflow-hidden rounded-2xl rounded-tl-sm border border-border bg-card/72 px-5 py-4"
            >
              <div class="flex items-center gap-2.5 text-sm text-muted-foreground">
                <div class="relative w-4 h-4 flex-shrink-0">
                  <div class="absolute inset-0 rounded-full border-2 border-primary/20" />
                  <div
                    class="absolute inset-0 animate-spin rounded-full border-2 border-primary border-t-transparent"
                  />
                </div>
                <span class="text-muted-foreground">{{ getCurrentStage(progressSteps) }}</span>
              </div>
            </div>
          </div>

          <div ref="messagesEndRef" />
        </ChatScrollArea>

        <div
          v-if="showJumpToBottom"
          class="pointer-events-none absolute bottom-[5.75rem] right-4 z-20 md:bottom-24 md:right-6"
        >
          <button
            type="button"
            class="pointer-events-auto inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 text-xs text-muted-foreground hover:bg-muted shadow-sm"
            aria-label="查看最新消息"
            @click="
              requestScrollToBottom('smooth');
              scrollToBottom('smooth');
            "
          >
            <ArrowDown class="size-3.5" />
            有新消息
          </button>
        </div>

        <div class="border-t border-border bg-card/88 p-4 md:p-6 relative z-20">
          <div class="space-y-3">
            <ApiErrorAlert
              v-if="chatError"
              :error="chatError"
            />
            <Alert
              v-if="isFollowUpContextLoading"
              class="rounded-xl px-3 py-2 text-xs shadow-none"
            >
              <AlertTitle>追问上下文加载中</AlertTitle>
              <AlertDescription>正在加载历史分析上下文；现在可直接发送追问。</AlertDescription>
            </Alert>

            <div
              v-if="skills.length > 0"
              class="flex flex-wrap items-start gap-x-5 gap-y-2"
            >
              <span
                class="text-xs text-muted-foreground font-medium uppercase tracking-wider flex-shrink-0 mt-1"
              >
                策略
              </span>
              <label class="flex items-center gap-1.5 text-sm cursor-pointer group mt-0.5">
                <input
                  type="checkbox"
                  name="general-analysis"
                  value=""
                  :checked="selectedSkillIds.length === 0"
                  class="accent-primary"
                  @change="selectedSkillIds = []"
                />
                <span
                  :class="[
                    'transition-colors text-sm',
                    selectedSkillIds.length === 0
                      ? 'text-foreground font-medium'
                      : 'text-muted-foreground group-hover:text-foreground',
                  ]"
                >
                  通用分析
                </span>
              </label>
              <label
                v-for="s in skills"
                :key="s.id"
                :class="[
                  'flex items-center gap-1.5 cursor-pointer group relative mt-0.5',
                  !selectedSkillIdSet.has(s.id) && skillLimitReached
                    ? 'opacity-60 cursor-not-allowed'
                    : '',
                ]"
                @mouseenter="showSkillDesc = s.id"
                @mouseleave="showSkillDesc = null"
              >
                <input
                  type="checkbox"
                  name="skills"
                  :value="s.id"
                  :checked="selectedSkillIdSet.has(s.id)"
                  :disabled="!selectedSkillIdSet.has(s.id) && skillLimitReached"
                  class="accent-primary"
                  @change="toggleSkillSelection(s.id)"
                />
                <span
                  :class="[
                    'transition-colors text-sm',
                    selectedSkillIdSet.has(s.id)
                      ? 'text-foreground font-medium'
                      : 'text-muted-foreground group-hover:text-foreground',
                  ]"
                >
                  {{ s.name }}
                </span>
                <div
                  v-if="showSkillDesc === s.id && s.description"
                  class="absolute z-50 max-w-64 rounded-lg border bg-popover p-2 text-xs text-popover-foreground shadow-md"
                >
                  <p class="font-medium">{{ s.name }}</p>
                  <p>{{ s.description }}</p>
                </div>
              </label>
            </div>

            <div class="flex items-end gap-3">
              <textarea
                v-model="input"
                :disabled="loading"
                rows="1"
                placeholder="例如：分析 600519 / 茅台现在适合买入吗？ (Enter 发送, Shift+Enter 换行)"
                class="border-input bg-background shadow-xs focus:border-ring focus:ring-2 focus:ring-ring/30 flex-1 min-h-[44px] max-h-[200px] rounded-xl border bg-transparent px-4 py-2.5 text-sm transition-all focus:outline-none resize-none disabled:cursor-not-allowed disabled:opacity-60"
                style="height: auto"
                @keydown="handleKeyDown"
                @input="onTextareaInput"
              />
              <LoadingButton
                variant="default"
                :disabled="!input.trim() || loading"
                :loading="loading"
                class="flex-shrink-0"
                @click="handleSend()"
              >
                发送
              </LoadingButton>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

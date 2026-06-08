<script setup lang="ts">
import { useTheme } from '@/composables/useTheme';
import { getSentimentLabel, type ReportLanguage } from '@/types/analysis';
import { cn } from '@/utils/cn';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import { computed, onUnmounted, ref, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    score: number;
    size?: 'sm' | 'md' | 'lg';
    showLabel?: boolean;
    class?: string;
    language?: ReportLanguage;
  }>(),
  {
    size: 'md',
    showLabel: true,
    class: '',
    language: 'zh',
  },
);

const { resolvedTheme } = useTheme();

const animatedScore = ref(0);
const displayScore = ref(0);
let animationRef: number | null = null;
const prevScore = ref(0);

function runAnimation() {
  if (animationRef !== null) {
    cancelAnimationFrame(animationRef);
    animationRef = null;
  }

  const startScore = prevScore.value;
  const endScore = props.score;
  const duration = 1000;
  const startTime = performance.now();

  const animate = (currentTime: number) => {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const easeOut = 1 - Math.pow(1 - progress, 3);
    const currentScore = startScore + (endScore - startScore) * easeOut;
    animatedScore.value = currentScore;
    displayScore.value = Math.round(currentScore);

    if (progress < 1) {
      animationRef = requestAnimationFrame(animate);
    } else {
      prevScore.value = endScore;
      animationRef = null;
    }
  };

  animationRef = requestAnimationFrame(animate);
}

watch(
  () => props.score,
  () => {
    runAnimation();
  },
  { immediate: true },
);

onUnmounted(() => {
  if (animationRef !== null) {
    cancelAnimationFrame(animationRef);
  }
});

const reportLanguage = computed(() => normalizeReportLanguage(props.language));
const text = computed(() => getReportText(reportLanguage.value));
const label = computed(() => getSentimentLabel(props.score, reportLanguage.value));

const isDark = computed(() => resolvedTheme.value === 'dark');

const sizeConfig = {
  sm: { width: 100, stroke: 8, fontSize: 'text-2xl', labelSize: 'text-xs', gap: 6 },
  md: { width: 140, stroke: 10, fontSize: 'text-4xl', labelSize: 'text-sm', gap: 8 },
  lg: { width: 180, stroke: 12, fontSize: 'text-5xl', labelSize: 'text-base', gap: 10 },
};

type SentimentKey = 'greed' | 'neutral' | 'fear';

const sentimentConfig = {
  greed: {
    color: '#fa739a',
    glowFilter: 'rgba(250, 115, 154, 0.46)',
    lightColor: '#ff9db7',
    lightEndColor: '#fa739a',
  },
  neutral: {
    color: '#0087bd',
    glowFilter: 'rgba(0, 135, 189, 0.36)',
    lightColor: '#2da6d7',
    lightEndColor: '#0087bd',
  },
  fear: {
    color: '#ff4466',
    glowFilter: 'rgba(255, 68, 102, 0.66)',
    lightColor: '#fb7185',
    lightEndColor: '#e11d48',
  },
};

function getSentimentKey(s: number): SentimentKey {
  if (s >= 60) return 'greed';
  if (s >= 40) return 'neutral';
  return 'fear';
}

const layout = computed(() => sizeConfig[props.size]);
const radius = computed(() => (layout.value.width - layout.value.stroke) / 2);
const circumference = computed(() => 2 * Math.PI * radius.value);
const arcLength = computed(() => circumference.value * 0.75);
const progress = computed(() => (animatedScore.value / 100) * arcLength.value);

const sentimentKey = computed(() => getSentimentKey(animatedScore.value));
const colors = computed(() => sentimentConfig[sentimentKey.value]);
const uniqueId = computed(
  () => `${sentimentKey.value}-${props.score}-${animatedScore.value.toFixed(0)}`,
);

const gaugeTheme = computed(() =>
  isDark.value
    ? {
        svgFilter: `drop-shadow(0 0 12px ${colors.value.glowFilter})`,
        glowBlur: 4,
        glowOpacity: 0.3,
        glowStrokeExtra: layout.value.gap,
        valueTextShadow: `0 0 30px ${colors.value.glowFilter}`,
      }
    : {
        svgFilter: `drop-shadow(0 0 8px ${colors.value.glowFilter.replace('0.66', '0.28')})`,
        glowBlur: 3.4,
        glowOpacity: 0.26,
        glowStrokeExtra: Math.max(3, layout.value.gap * 0.55),
        valueTextShadow: `0 0 16px ${colors.value.glowFilter.replace('0.66', '0.22')}`,
      },
);
</script>

<template>
  <div :class="cn('flex flex-col items-center', props.class)">
    <span v-if="showLabel" class="label-uppercase mb-3 text-secondary-text">
      {{ text.fearGreedIndex }}
    </span>

    <div class="relative" :style="{ width: `${layout.width}px`, height: `${layout.width}px` }">
      <svg
        class="gauge-ring overflow-visible"
        :width="layout.width"
        :height="layout.width"
        :style="gaugeTheme.svgFilter ? { filter: gaugeTheme.svgFilter } : {}"
      >
        <defs>
          <linearGradient :id="`gauge-gradient-${uniqueId}`" x1="0%" y1="0%" x2="100%" y2="100%">
            <template v-if="isDark">
              <stop offset="0%" :stop-color="colors.color" stop-opacity="0.6" />
              <stop offset="100%" :stop-color="colors.color" stop-opacity="1" />
            </template>
            <template v-else>
              <stop offset="0%" :stop-color="colors.lightColor" stop-opacity="0.9" />
              <stop offset="100%" :stop-color="colors.lightEndColor" stop-opacity="1" />
            </template>
          </linearGradient>

          <filter :id="`gauge-glow-${uniqueId}`">
            <feGaussianBlur :stdDeviation="gaugeTheme.glowBlur" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <circle
          :cx="layout.width / 2"
          :cy="layout.width / 2"
          :r="radius"
          fill="none"
          stroke="rgba(255, 255, 255, 0.05)"
          :stroke-width="layout.stroke"
          stroke-linecap="round"
          :stroke-dasharray="`${arcLength} ${circumference}`"
          :transform="`rotate(135 ${layout.width / 2} ${layout.width / 2})`"
        />

        <circle
          :cx="layout.width / 2"
          :cy="layout.width / 2"
          :r="radius"
          fill="none"
          :stroke="isDark ? colors.color : colors.lightColor"
          :stroke-width="layout.stroke + gaugeTheme.glowStrokeExtra"
          stroke-linecap="round"
          :stroke-dasharray="`${progress} ${circumference}`"
          :transform="`rotate(135 ${layout.width / 2} ${layout.width / 2})`"
          :opacity="gaugeTheme.glowOpacity"
          :filter="`url(#gauge-glow-${uniqueId})`"
        />

        <circle
          :cx="layout.width / 2"
          :cy="layout.width / 2"
          :r="radius"
          fill="none"
          :stroke="`url(#gauge-gradient-${uniqueId})`"
          :stroke-width="layout.stroke"
          stroke-linecap="round"
          :stroke-dasharray="`${progress} ${circumference}`"
          :transform="`rotate(135 ${layout.width / 2} ${layout.width / 2})`"
        />
      </svg>

      <div class="absolute inset-0 flex flex-col items-center justify-center">
        <span
          :class="cn('font-bold', layout.fontSize, isDark ? 'text-white' : 'text-foreground')"
          :style="gaugeTheme.valueTextShadow ? { textShadow: gaugeTheme.valueTextShadow } : {}"
        >
          {{ displayScore }}
        </span>
        <span
          v-if="showLabel"
          :class="`${layout.labelSize} mt-1 font-semibold`"
          :style="{ color: isDark ? colors.color : colors.lightEndColor }"
        >
          {{ label.toUpperCase() }}
        </span>
      </div>
    </div>
  </div>
</template>

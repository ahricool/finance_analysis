import { defineStore } from 'pinia';
import { ref, watch } from 'vue';

export type DisplayTimezone = 'Asia/Shanghai' | 'America/New_York';

export const DISPLAY_TIMEZONES: Array<{
  value: DisplayTimezone;
  label: string;
  shortLabel: string;
}> = [
  { value: 'Asia/Shanghai', label: '北京时间', shortLabel: 'BJT' },
  { value: 'America/New_York', label: '美东时间', shortLabel: 'ET' },
];

export const DEFAULT_DISPLAY_TIMEZONE: DisplayTimezone = 'Asia/Shanghai';

const STORAGE_KEY = 'display_timezone';

function isDisplayTimezone(value: unknown): value is DisplayTimezone {
  return value === 'Asia/Shanghai' || value === 'America/New_York';
}

function readStoredTimezone(): DisplayTimezone {
  if (typeof localStorage === 'undefined') return DEFAULT_DISPLAY_TIMEZONE;
  const raw = localStorage.getItem(STORAGE_KEY);
  return isDisplayTimezone(raw) ? raw : DEFAULT_DISPLAY_TIMEZONE;
}

export const useTimezoneStore = defineStore('timezone', () => {
  const displayTimezone = ref<DisplayTimezone>(readStoredTimezone());

  function setDisplayTimezone(timezone: DisplayTimezone) {
    displayTimezone.value = timezone;
  }

  watch(
    displayTimezone,
    (value) => {
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(STORAGE_KEY, value);
      }
    },
    { immediate: true },
  );

  return {
    displayTimezone,
    setDisplayTimezone,
  };
});

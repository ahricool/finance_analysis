<script setup lang="ts">
import { computed } from 'vue';
import { Minus, Plus } from 'lucide-vue-next';
import { useStockDetail } from '@/composables/useStockDetail';
import { pct, tone } from './labels';
import type { IndustryMapNode } from './industryMap';

const props = defineProps<{ node: IndustryMapNode; expanded: boolean; compact: boolean }>();
const emit = defineEmits<{ toggle: [id: string] }>();
const detail = useStockDetail();
const branch = computed(() => props.node.kind !== 'stock' && props.node.children.length > 0);
const chineseName = computed(() => {
  const name = props.node.kind === 'stock' ? props.node.name?.trim() : null;
  return name && /\p{Script=Han}/u.test(name) ? name : null;
});

function select() {
  const node = props.node;
  if (node.kind === 'stock') {
    detail.open({ code: node.id, name: node.name, marketType: 'US' });
  } else {
    emit('toggle', node.id);
  }
}
</script>

<template>
  <button
    type="button"
    class="map-node"
    :class="[`map-${node.kind}`, { 'map-compact': compact }]"
    :aria-expanded="branch ? expanded : undefined"
    :disabled="node.kind !== 'stock' && !branch"
    :data-map-id="node.id"
    :data-map-kind="node.kind"
    @click="select"
  >
    <span class="map-identity">
      <component
        :is="expanded ? Minus : Plus"
        v-if="branch"
        class="map-toggle"
        aria-hidden="true"
      />
      <span class="map-label">{{ node.label }}</span>
      <span
        v-if="chineseName"
        class="map-name"
      >{{ chineseName }}</span>
    </span>
    <span class="map-quote">
      <span
        class="font-semibold"
        :class="tone(node.change)"
      >{{ pct(node.change) }}</span>
      <span
        v-if="node.kind !== 'stock' && node.coverage && node.coverage.quoted < node.coverage.total"
        class="map-coverage"
      >
        <span class="sr-only">有效报价</span>{{ node.coverage.quoted }}/{{ node.coverage.total }}
      </span>
    </span>
  </button>
</template>

<style scoped>
.map-node {
  position: absolute;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.45rem;
  min-inline-size: 0;
  padding: 0 0.25rem 0.37rem;
  border: 0;
  background: transparent;
  color: hsl(var(--card-foreground));
  font-size: 0.8125rem;
  line-height: 1.15;
  text-align: start;
  transform: translateY(-50%);
}

.map-node::after {
  position: absolute;
  inset-inline: 0;
  inset-block-end: var(--map-underline-bottom);
  border-block-end: 1px solid hsl(var(--foreground) / 0.22);
  content: '';
}

.map-node:enabled {
  cursor: pointer;
}

.map-node:focus-visible {
  outline: none;
}

.map-node:focus-visible .map-label {
  text-decoration: underline;
  text-underline-offset: 0.12em;
}

.map-root {
  font-size: 0.875rem;
}

.map-root::after {
  border-color: hsl(var(--foreground) / 0.5);
}

.map-node:enabled:hover::after,
.map-node:focus-visible::after {
  border-color: hsl(var(--ring));
}

.map-identity {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  min-inline-size: 0;
}

.map-toggle {
  flex: none;
  inline-size: 0.8rem;
  block-size: 0.8rem;
  color: hsl(var(--muted-foreground));
}

.map-label {
  font-weight: 600;
  overflow-wrap: anywhere;
}

.map-root .map-label,
.map-stock .map-label {
  white-space: nowrap;
}

.map-stock .map-label {
  font-variant-numeric: tabular-nums;
}

.map-name {
  color: hsl(var(--muted-foreground));
  overflow-wrap: anywhere;
}

.map-quote {
  display: block;
  flex: none;
  white-space: nowrap;
  text-align: end;
  font-variant-numeric: tabular-nums;
}

.map-coverage {
  display: block;
  margin-block-start: 0.14rem;
  color: hsl(var(--muted-foreground));
  font-size: 0.625rem;
}

.map-compact {
  flex-direction: column;
  justify-content: flex-end;
  align-items: stretch;
  gap: 0.15rem;
  padding-inline: 0.16rem;
  font-size: 0.6875rem;
}

.map-compact .map-identity {
  gap: 0.13rem;
}

.map-compact .map-toggle {
  inline-size: 0.58rem;
  block-size: 0.58rem;
}

.map-compact .map-quote {
  font-size: 0.625rem;
}

.map-stock.map-compact .map-identity {
  flex-wrap: wrap;
}

.map-stock.map-compact .map-name {
  flex: 1 0 100%;
}
</style>

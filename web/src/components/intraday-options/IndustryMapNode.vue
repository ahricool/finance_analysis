<script setup lang="ts">
import { ChevronDown, ChevronRight } from 'lucide-vue-next';
import { pct, tone } from './labels';
import type { IndustryMapNode as Node } from './industryMap';

defineProps<{ node: Node; expanded: ReadonlySet<string> }>();
defineEmits<{ toggle: [id: string] }>();
</script>

<template>
  <div :class="['map-branch', `map-${node.kind}`]">
    <button
      v-if="node.kind !== 'stock' && node.children.length"
      type="button"
      class="map-node focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      :aria-expanded="expanded.has(node.id)"
      @click="$emit('toggle', node.id)"
    >
      <component
        :is="expanded.has(node.id) ? ChevronDown : ChevronRight"
        class="mt-0.5 size-4 shrink-0 text-muted-foreground"
        aria-hidden="true"
      />
      <span class="map-label min-w-0 break-words">{{ node.label }}</span>
      <span class="map-change">
        <span :class="tone(node.change)">{{ pct(node.change) }}</span>
        <span
          v-if="node.coverage && node.coverage.quoted < node.coverage.total"
          class="block text-right text-xs font-normal text-muted-foreground"
        >
          <span class="sr-only">有效报价</span>{{ node.coverage.quoted }}/{{ node.coverage.total }}
        </span>
      </span>
    </button>
    <div
      v-else
      class="map-node"
    >
      <span>{{ node.label }}</span>
      <span
        class="map-change"
        :class="tone(node.change)"
      >{{ pct(node.change) }}</span>
      <span
        v-if="node.kind === 'stock' && node.marketCap === null"
        class="sr-only"
      >暂无市值</span>
    </div>
    <ul
      v-if="node.kind !== 'stock' && expanded.has(node.id) && node.children.length"
      class="map-children"
    >
      <li
        v-for="child in node.children"
        :key="child.id"
      >
        <IndustryMapNode
          :node="child"
          :expanded="expanded"
          @toggle="$emit('toggle', $event)"
        />
      </li>
    </ul>
  </div>
</template>

<style scoped>
.map-branch {
  --gap: 0.85rem;
  --connector: hsl(var(--muted-foreground) / 0.43);
  --node-center: 1.25rem;
  display: flex;
  align-items: flex-start;
}

.map-node {
  display: flex;
  align-items: flex-start;
  flex: none;
  gap: 0.4rem;
  padding: 0.55rem 0.65rem;
  min-inline-size: 0;
  border: 1px solid hsl(var(--border));
  border-radius: var(--radius-md);
  background: hsl(var(--card));
  color: hsl(var(--card-foreground));
  font-size: 0.875rem;
  line-height: 1.25rem;
  text-align: start;
}

button.map-node {
  cursor: pointer;
  font-weight: 500;
}

button.map-node:hover {
  border-color: hsl(var(--ring));
  background: hsl(var(--accent));
  color: hsl(var(--accent-foreground));
}

.map-root > .map-node {
  inline-size: 9rem;
  border-color: color-mix(in oklab, hsl(var(--primary)) 42%, hsl(var(--border)));
  font-weight: 600;
}

.map-root > .map-node > .map-label { white-space: nowrap; }
.map-sector > .map-node { inline-size: 10.5rem; }
.map-industry > .map-node { inline-size: 15rem; }
.map-stock > .map-node { inline-size: 8.5rem; }

.map-change {
  margin-inline-start: auto;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.map-children {
  position: relative;
  margin-inline-start: var(--gap);
  padding-inline-start: var(--gap);
}

.map-children::before,
.map-children > li::before {
  content: "";
  position: absolute;
  inset-block-start: var(--node-center);
  inset-inline-start: calc(-1 * var(--gap));
  inline-size: var(--gap);
  border-block-start: 1px solid var(--connector);
}

.map-children > li {
  position: relative;
}

.map-children > li:not(:last-child) {
  padding-block-end: 0.5rem;
}

.map-children > li::after {
  content: "";
  position: absolute;
  inset-block: 0;
  inset-inline-start: calc(-1 * var(--gap));
  border-inline-start: 1px solid var(--connector);
}

.map-children > li:first-child::after { inset-block-start: var(--node-center); }
.map-children > li:last-child::after { inset-block-end: calc(100% - var(--node-center)); }

@container (width < 49rem) {
  .map-branch { display: block; }
  .map-branch > .map-node { inline-size: 100%; }
  .map-children { margin-inline-start: 0.75rem; }
  .map-children::before { display: none; }
  .map-children > li:first-child { padding-block-start: 0.5rem; }
  .map-children > li:first-child::before { inset-block-start: calc(var(--node-center) + 0.5rem); }
  .map-children > li:first-child::after { inset-block-start: 0; }
  .map-children > li:first-child:last-child::after {
    inset-block-end: calc(100% - var(--node-center) - 0.5rem);
  }
}
</style>

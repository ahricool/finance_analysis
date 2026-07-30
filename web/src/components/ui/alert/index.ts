import type { VariantProps } from 'class-variance-authority';
import { cva } from 'class-variance-authority';
export { default as Alert } from './Alert.vue';
export { default as AlertDescription } from './AlertDescription.vue';
export { default as AlertTitle } from './AlertTitle.vue';
export const alertVariants = cva(
  'group/alert relative grid w-full gap-0.5 rounded-lg border bg-card px-4 py-3 text-left text-sm has-[>svg]:grid-cols-[auto_1fr] has-[>svg]:gap-x-2.5 [&>svg]:row-span-2 [&>svg]:size-4 [&>svg]:translate-y-0.5',
  { variants: { variant: { default: 'text-card-foreground', destructive: 'text-destructive [&>svg]:text-current' } }, defaultVariants: { variant: 'default' } },
);
export type AlertVariants = VariantProps<typeof alertVariants>;

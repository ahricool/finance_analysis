import { flushPromises, mount } from '@vue/test-utils';
import { defineComponent, ref } from 'vue';
import { describe, expect, it, vi } from 'vitest';
import AppConfirmDialog from '../AppConfirmDialog.vue';

describe('AppConfirmDialog', () => {
  it('opens from controlled state and confirms the action', async () => {
    const onConfirm = vi.fn();
    const confirmedWhileOpen = ref(false);
    const wrapper = mount(
      defineComponent({
        components: { AppConfirmDialog },
        setup() {
          const open = ref(false);
          function confirm() {
            confirmedWhileOpen.value = open.value;
            onConfirm();
          }
          return { confirm, open };
        },
        template: `
          <button type="button" @click="open = true">open</button>
          <AppConfirmDialog
            :open="open"
            title="Run task"
            description="Confirm task run"
            @update:open="open = $event"
            @confirm="confirm"
          />
        `,
      }),
      { attachTo: document.body },
    );

    await wrapper.get('button').trigger('click');
    await flushPromises();

    const dialog = document.body.querySelector('[role="alertdialog"]');
    expect(dialog).not.toBeNull();

    const confirmButton = Array.from(dialog?.querySelectorAll('button') ?? []).find(
      (button) => button.textContent?.trim() === '确定',
    );
    expect(confirmButton).toBeDefined();
    confirmButton?.click();
    await flushPromises();

    expect(onConfirm).toHaveBeenCalledOnce();
    expect(confirmedWhileOpen.value).toBe(true);
    wrapper.unmount();
  });
});

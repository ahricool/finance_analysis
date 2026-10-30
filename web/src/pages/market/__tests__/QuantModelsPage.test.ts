import { mount, flushPromises } from '@vue/test-utils';
import { createRouter, createMemoryHistory } from 'vue-router';
import { beforeEach, expect, it, vi } from 'vitest';
import QuantModelsPage from '../quant/QuantModelsPage.vue';
import { quantApi } from '@/api/quant';
vi.mock('@/api/quant', () => ({ quantApi: { models:vi.fn(), releases:vi.fn(), preflight:vi.fn(), experiment:vi.fn(), publishRelease:vi.fn() } }));
beforeEach(()=>{vi.clearAllMocks(); vi.mocked(quantApi.models).mockResolvedValue([]); vi.mocked(quantApi.releases).mockResolvedValue([]);});
async function page() {
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/research/quant/models',component:QuantModelsPage}]});
 await router.push('/research/quant/models?market=US');
 const wrapper=mount(QuantModelsPage,{global:{plugins:[router]}}); await flushPromises(); return {wrapper,router};
}
it('shows experiment workflow without dataset management and requires successful preflight',async()=>{
 const {wrapper}=await page();
 await wrapper.findAll('button').find(x=>x.text()==='创建训练实验')!.trigger('click');
 expect(wrapper.text()).not.toContain('使用此数据集训练');
 expect(wrapper.findAll('button').find(x=>x.text()==='提交双模型训练')!.attributes('disabled')).toBeDefined();
 vi.mocked(quantApi.preflight).mockRejectedValue(new Error('历史不足'));
 await wrapper.findAll('button').find(x=>x.text()==='检查训练数据')!.trigger('click'); await flushPromises();
 expect(quantApi.experiment).not.toHaveBeenCalled(); wrapper.unmount();
});
it('discards old market responses',async()=>{
 let resolve!: (value: never[])=>void;
 vi.mocked(quantApi.models).mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));
 const {wrapper,router}=await page();
 await router.push('/research/quant/models?market=CN'); await flushPromises(); resolve([]); await flushPromises();
 expect(quantApi.models).toHaveBeenLastCalledWith('CN'); expect(wrapper.text()).toContain('暂无训练记录'); wrapper.unmount();
});
it('submits a checked experiment and clears busy state after refresh',async()=>{
 const {wrapper}=await page();
 await wrapper.findAll('button').find(x=>x.text()==='创建训练实验')!.trigger('click');
 vi.mocked(quantApi.preflight).mockResolvedValue({sessions:1300,effectiveFrom:'2021-04-01',labelCutoff:'2026-01-01',initialTrainEnd:'2024-04-01',memberCount:100,eligibleCount:100,coverage:1,warning:''});
 await wrapper.findAll('button').find(x=>x.text()==='检查训练数据')!.trigger('click'); await flushPromises();
 await wrapper.findAll('button').find(x=>x.text()==='提交双模型训练')!.trigger('click'); await flushPromises();
 expect(quantApi.experiment).toHaveBeenCalledTimes(1);
 expect(wrapper.text()).toContain('训练实验已提交');
 expect(wrapper.findAll('button').find(x=>x.text()==='创建训练实验')!.attributes('disabled')).toBeUndefined();
 wrapper.unmount();
});

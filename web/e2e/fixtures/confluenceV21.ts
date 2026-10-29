import legacy from './confluenceV2';
const old = legacy.items[0]!;
const macro = { ...old.signals.macro, strength: 74, score: 11.1, contribution: 11.68,
  evidence: { ...old.signals.macro.evidence, adaptation_score: 74, macro_method: 'sector_macro_v1', adaptation_reason: '50为中性，相对适配不代表绝对收益',
    profiles: [{ key: 'cn_growth', name: 'A股成长风格', reason: '全球风险偏好对成长风格的弱代理，不代表国内流动性', coverage: 1, strength: 74, missing_factors: [],
      industries: [{ industry_name: '半导体', industry_code: '881121.TI' }], terms: [{ key: 'risk', label: '全球风险偏好', value: 80, coefficient: .8, contribution: 24 }] }] },
  reasons: ['整体风险偏好仅作背景；宏观15%使用所属行业适配度，非收益概率'] };
export default { ...legacy, algorithm_version: 'confluence_v2_1',
  items: [{ ...old, confluence_score: 84, signals: { ...old.signals, macro } }] };

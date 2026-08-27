# US ETF Momentum Rotation 策略对比

## Baseline 年化低的主要原因
Entry#1 在 T 收盘到 T+1 开盘的隔夜收益均值为 0.13%，而策略只能在次日开盘买入，因此隔夜缺口会被吃掉，这是 Baseline 年化偏弱的重要来源。
Baseline CAGR=12.49%，换手=45.06%，平均持仓天数=3.235，年化交易次数=112.696。若换手高、持仓短，说明 Entry Rank 前二过滤仍过于敏感，容易在噪声排名上反复换仓。
Entry#1 次日开盘到收盘均值 -0.04%，可用于判断日内是否还能兑现动量。

## Top1 还是 Top3
Top1 代表：A_baseline cagr=12.49%, B_entry1_mom10 cagr=2.78%, C_entry1_mom20 cagr=30.01%。最佳 C_entry1_mom20。
Top3 代表：D_top3_mom10 cagr=12.56%, E_top3_mom20 cagr=23.58%, F_top3_absolute cagr=18.98%。最佳 E_top3_mom20。
Top1 最佳 C_entry1_mom20 Sharpe=1.019；Top3 最佳 E_top3_mom20 Sharpe=0.955。当前样本更看好Top1 最佳（C_entry1_mom20）。

## Momentum 10 vs 20 退出
单票：B_entry1_mom10 cagr=2.78%，C_entry1_mom20 为 30.01%。按该指标更优的是 C_entry1_mom20。 Sharpe：B_entry1_mom10 sharpe=0.242，C_entry1_mom20 为 1.019。按该指标更优的是 C_entry1_mom20。 回撤：B_entry1_mom10 max_drawdown=-50.11%，C_entry1_mom20 为 -34.65%。按该指标更优的是 C_entry1_mom20。 换手：B_entry1_mom10 turnover=16.23%，C_entry1_mom20 为 8.43%。按该指标更优的是 C_entry1_mom20。
Top3：D_top3_mom10 cagr=12.56%，E_top3_mom20 为 23.58%。按该指标更优的是 E_top3_mom20。 Sharpe：D_top3_mom10 sharpe=0.583，E_top3_mom20 为 0.955。按该指标更优的是 E_top3_mom20。 回撤：D_top3_mom10 max_drawdown=-36.06%，E_top3_mom20 为 -31.90%。按该指标更优的是 E_top3_mom20。 换手：D_top3_mom10 turnover=16.54%，E_top3_mom20 为 8.88%。按该指标更优的是 E_top3_mom20。
若 Momentum 10 换手明显更高而收益没有更好，则 20 作为退出阈值更合理；反之说明动量衰减很快，应更早离场。

## Absolute Filter 是否有效
F_top3_absolute cagr=18.98%，E_top3_mom20 为 23.58%。按该指标更优的是 E_top3_mom20。 Sharpe F_top3_absolute sharpe=0.801，E_top3_mom20 为 0.955。按该指标更优的是 E_top3_mom20。 回撤 F_top3_absolute max_drawdown=-35.02%，E_top3_mom20 为 -31.90%。按该指标更优的是 E_top3_mom20。 胜率 F_top3_absolute win_rate=46.10%，E_top3_mom20 为 48.12%。按该指标更优的是 E_top3_mom20。
若 F 相对 E 提高胜率或降低回撤，说明 ret_5d>0 且站上 MA20 的过滤有效；若收益下降很多，则过滤过严、错过主升。

## Risk-Off 是否改善回撤
H_f_riskoff max_drawdown=-32.53%，F_top3_absolute 为 -35.02%。按该指标更优的是 H_f_riskoff。 CAGR H_f_riskoff cagr=16.56%，F_top3_absolute 为 18.98%。按该指标更优的是 F_top3_absolute。 现金比例 H_f_riskoff cash_ratio=5.50%，F_top3_absolute 为 1.75%。按该指标更优的是 H_f_riskoff。
若 H 回撤更小且现金比例更高，说明 30% 广度过滤起到避险作用；若回撤几乎不变，则该样本里系统性下跌不够集中。

## Stop 是否改善 downside
回撤 G_f_stop max_drawdown=-27.02%，F_top3_absolute 为 -35.02%。按该指标更优的是 G_f_stop。 MAE G_f_stop mae=-2.76%，F_top3_absolute 为 -3.25%。按该指标更优的是 G_f_stop。 CAGR G_f_stop cagr=14.70%，F_top3_absolute 为 18.98%。按该指标更优的是 F_top3_absolute。
止损只上移、以 T+1 开盘成交价为锚。若 MAE/回撤改善但 CAGR 明显变差，说明止损在正常波动里被扫出。

## Hysteresis 是否减少无效换仓
换手 I_hysteresis turnover=6.86%，D_top3_mom10 为 16.54%。按该指标更优的是 I_hysteresis。 相对 D；相对 E：I_hysteresis turnover=6.86%，E_top3_mom20 为 8.88%。按该指标更优的是 I_hysteresis。 持仓天数 I_hysteresis avg_holding_days=20.887，E_top3_mom20 为 16.247。按该指标更优的是 I_hysteresis。
若 I 换手下降而 Sharpe 不差，说明 16-20 观察带减少了噪声退出。

## 推荐继续使用
按 Sharpe 优先（同分看 CAGR），推荐 **I_hysteresis** (Hysteresis Top3)：CAGR=30.99%，Sharpe=1.163，MaxDD=-21.55%，换手=6.86%。
以上均为固定规则对比，没有做参数搜索。

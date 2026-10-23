import type { HeatmapMarket, HeatmapSnapshot } from '@/api/marketHeatmap';

// Synthetic review fixtures. Caps are in billions of local currency; no live quotes.
const us = [
  ['科技', 'NVDA,NVIDIA,4500;MSFT,Microsoft,3800;AAPL,Apple,3400;AVGO,Broadcom,1500;TSM,台积电,1400;ORCL,Oracle,800;AMD,AMD,400;PLTR,Palantir,350;MU,Micron,280;CSCO,Cisco,250;CRM,Salesforce,220;INTC,Intel,180;ADBE,Adobe,150;QCOM,Qualcomm,140;TXN,Texas Instruments,130;ARM,Arm,120'],
  ['金融服务', 'BRK.B,伯克希尔,1100;JPM,摩根大通,850;V,Visa,650;MA,Mastercard,520;BAC,美国银行,360;WFC,富国银行,260;GS,高盛,230;MS,摩根士丹利,210;AXP,美国运通,200;C,花旗,170;BLK,贝莱德,160;SCHW,嘉信,150;SPGI,标普全球,140;CME,芝商所,100'],
  ['通信服务', 'GOOGL,Alphabet A,2200;GOOG,Alphabet C,1900;META,Meta,1700;NFLX,Netflix,430;TMUS,T-Mobile,240;DIS,Disney,200;VZ,Verizon,180;T,AT&T,170;CMCSA,Comcast,120'],
  ['可选消费', 'AMZN,Amazon,2400;TSLA,Tesla,1200;HD,Home Depot,380;MCD,McDonalds,220;PDD,拼多多,180;BABA,阿里巴巴,170;LOW,Lowes,140;BKNG,Booking,130;TJX,TJX,110;NKE,Nike,80;SBUX,Starbucks,70'],
  ['医疗保健', 'LLY,礼来,900;JNJ,强生,420;ABBV,艾伯维,360;UNH,联合健康,300;MRK,默沙东,240;ABT,雅培,230;AMGN,安进,170;TMO,赛默飞,160;ISRG,直觉外科,150;PFE,辉瑞,140;GILD,吉利德,130;VRTX,福泰,120;MDT,美敦力,110'],
  ['工业', 'GE,GE Aerospace,280;CAT,卡特彼勒,250;RTX,雷神,210;HON,霍尼韦尔,160;BA,波音,150;UNP,联合太平洋,140;ETN,伊顿,130;DE,迪尔,120;LMT,洛克希德,110;UPS,UPS,90'],
  ['能源', 'XOM,埃克森美孚,520;CVX,雪佛龙,310;COP,康菲石油,140;EOG,EOG,70;SLB,斯伦贝谢,60;OXY,西方石油,55;MPC,马拉松,50;VLO,瓦莱罗,45'],
  ['日常消费', 'WMT,沃尔玛,800;COST,Costco,440;PG,宝洁,350;KO,可口可乐,300;PM,菲利普莫里斯,260;PEP,百事,210;MO,奥驰亚,90;MDLZ,亿滋,85'],
];
const cn = [
  ['电子', '688981,中芯国际,900;688256,寒武纪,600;002475,立讯精密,450;002371,北方华创,400;688041,海光信息,350;002415,海康威视,280;603501,豪威集团,190;688012,中微公司,180;002049,紫光国微,140;000725,京东方A,130;002241,歌尔股份,110;600584,长电科技,90;002156,通富微电,60;603986,兆易创新,55'],
  ['银行', '601398,工商银行,2800;601288,农业银行,2300;601939,建设银行,2100;601988,中国银行,1800;600036,招商银行,1100;601328,交通银行,600;601166,兴业银行,420;600000,浦发银行,340;000001,平安银行,280;002142,宁波银行,230;601169,北京银行,140;601009,南京银行,130;601838,成都银行,85'],
  ['食品饮料', '600519,贵州茅台,2200;000858,五粮液,550;600887,伊利股份,220;000568,泸州老窖,190;600809,山西汾酒,180;603288,海天味业,160;002304,洋河股份,110;600600,青岛啤酒,90;000596,古井贡酒,85'],
  ['电力设备', '300750,宁德时代,1600;300274,阳光电源,300;601012,隆基绿能,140;600406,国电南瑞,130;002129,TCL中环,80;300014,亿纬锂能,75;002709,天赐材料,60;601877,正泰电器,50;300124,汇川技术,45'],
  ['汽车', '002594,比亚迪,1100;600104,上汽集团,220;601127,赛力斯,210;000625,长安汽车,160;601633,长城汽车,150;600660,福耀玻璃,130;601689,拓普集团,100;002920,德赛西威,75'],
  ['医药生物', '600276,恒瑞医药,380;300760,迈瑞医疗,330;603259,药明康德,280;600436,片仔癀,160;300122,智飞生物,100;000538,云南白药,90;600085,同仁堂,70;300015,爱尔眼科,60;002007,华兰生物,50;600196,复星医药,45'],
  ['通信', '600941,中国移动,2100;601728,中国电信,600;300308,中际旭创,420;300502,新易盛,350;000063,中兴通讯,260;600050,中国联通,180;300394,天孚通信,110'],
  ['有色金属', '601899,紫金矿业,650;603993,洛阳钼业,260;600547,山东黄金,180;601600,中国铝业,160;002460,赣锋锂业,90;002466,天齐锂业,80;600362,江西铜业,70;600489,中金黄金,65'],
];
export function demoSnapshot(market: HeatmapMarket): HeatmapSnapshot {
  return { market, source: 'demo', generatedAt: '2026-10-24T02:00:00Z', dataAsOf: null, dataLatestAt: null,
    classificationObservedAt: null, minMarketCap: market === 'CN' ? 1e10 : 2e9, refreshSeconds: 900,
    excludedCount: 0, unclassifiedCount: 0,
    items: (market === 'US' ? us : cn).flatMap(([groupName, records], g) => records!.split(';').map((record, i) => {
      const [symbol, name, cap] = record.split(',');
      const suffix = market === 'US' ? 'US' : symbol!.startsWith('6') ? 'SH' : 'SZ';
      return { code: `${symbol}.${suffix}`, name: name!, marketCap: Number(cap) * 1e9, price: 100,
        changePct: i === 12 ? null : [1.11, -0.73, 0.67, 2.35, -2.99, 3.23, -1.25, 0, -0.56, 4.14, -3.85][(i + g * 3) % 11]!,
        groupCode: `group${g}`, groupName: groupName!, quoteTime: null };
    })) };
}

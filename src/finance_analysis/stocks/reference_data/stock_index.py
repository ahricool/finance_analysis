# -*- coding: utf-8 -*-
"""Versioned reference constituents used by market-data database seeds.

Nasdaq-100 was refreshed on 2026-06-18 from StockAnalysis.com. S&P 500 and
CSI 300 were refreshed on 2026-07-20 from the datasets/s-and-p-500-companies
constituent dataset and AKShare ``index_stock_cons_csindex('000300')`` respectively.
"""

NASDAQ100_STOCK_INDEX = {
    "NVDA": "NVIDIA Corporation",
    "GOOGL": "Alphabet Inc.",
    "GOOG": "Alphabet Inc.",
    "AAPL": "Apple Inc.",
    "MSFT": "Microsoft Corporation",
    "AMZN": "Amazon.com, Inc.",
    "AVGO": "Broadcom Inc.",
    "TSLA": "Tesla, Inc.",
    "META": "Meta Platforms, Inc.",
    "MU": "Micron Technology, Inc.",
    "WMT": "Walmart Inc.",
    "AMD": "Advanced Micro Devices, Inc.",
    "ASML": "ASML Holding N.V.",
    "INTC": "Intel Corporation",
    "AMAT": "Applied Materials, Inc.",
    "LRCX": "Lam Research Corporation",
    "CSCO": "Cisco Systems, Inc.",
    "ARM": "Arm Holdings plc",
    "COST": "Costco Wholesale Corporation",
    "NFLX": "Netflix, Inc.",
    "PLTR": "Palantir Technologies Inc.",
    "KLAC": "KLA Corporation",
    "TXN": "Texas Instruments Incorporated",
    "MRVL": "Marvell Technology, Inc.",
    "WDC": "Western Digital Corporation",
    "STX": "Seagate Technology Holdings plc",
    "LIN": "Linde plc",
    "PANW": "Palo Alto Networks, Inc.",
    "QCOM": "QUALCOMM Incorporated",
    "ADI": "Analog Devices, Inc.",
    "TMUS": "T-Mobile US, Inc.",
    "PEP": "PepsiCo, Inc.",
    "AMGN": "Amgen Inc.",
    "CRWD": "CrowdStrike Holdings, Inc.",
    "APP": "AppLovin Corporation",
    "GILD": "Gilead Sciences, Inc.",
    "HON": "Honeywell International Inc.",
    "ISRG": "Intuitive Surgical, Inc.",
    "SHOP": "Shopify Inc.",
    "BKNG": "Booking Holdings Inc.",
    "VRTX": "Vertex Pharmaceuticals Incorporated",
    "SBUX": "Starbucks Corporation",
    "PDD": "PDD Holdings Inc.",
    "CDNS": "Cadence Design Systems, Inc.",
    "FTNT": "Fortinet, Inc.",
    "MAR": "Marriott International, Inc.",
    "CEG": "Constellation Energy Corporation",
    "MNST": "Monster Beverage Corporation",
    "SNPS": "Synopsys, Inc.",
    "ADP": "Automatic Data Processing, Inc.",
    "CSX": "CSX Corporation",
    "ABNB": "Airbnb, Inc.",
    "MELI": "MercadoLibre, Inc.",
    "CMCSA": "Comcast Corporation",
    "DDOG": "Datadog, Inc.",
    "MDLZ": "Mondelez International, Inc.",
    "ADBE": "Adobe Inc.",
    "NXPI": "NXP Semiconductors N.V.",
    "ROST": "Ross Stores, Inc.",
    "INTU": "Intuit Inc.",
    "ORLY": "O'Reilly Automotive, Inc.",
    "DASH": "DoorDash, Inc.",
    "MPWR": "Monolithic Power Systems, Inc.",
    "AEP": "American Electric Power Company, Inc.",
    "CTAS": "Cintas Corporation",
    "WBD": "Warner Bros. Discovery, Inc.",
    "REGN": "Regeneron Pharmaceuticals, Inc.",
    "PCAR": "PACCAR Inc",
    "BKR": "Baker Hughes Company",
    "FANG": "Diamondback Energy, Inc.",
    "FAST": "Fastenal Company",
    "MCHP": "Microchip Technology Incorporated",
    "EA": "Electronic Arts Inc.",
    "FER": "Ferrovial N.V.",
    "XEL": "Xcel Energy Inc.",
    "EXC": "Exelon Corporation",
    "ODFL": "Old Dominion Freight Line, Inc.",
    "CCEP": "Coca-Cola Europacific Partners PLC",
    "IDXX": "IDEXX Laboratories, Inc.",
    "TTWO": "Take-Two Interactive Software, Inc.",
    "KDP": "Keurig Dr Pepper Inc.",
    "MSTR": "Strategy Inc",
    "ADSK": "Autodesk, Inc.",
    "ALNY": "Alnylam Pharmaceuticals, Inc.",
    "PYPL": "PayPal Holdings, Inc.",
    "PAYX": "Paychex, Inc.",
    "TRI": "Thomson Reuters Corporation",
    "AXON": "Axon Enterprise, Inc.",
    "ROP": "Roper Technologies, Inc.",
    "WDAY": "Workday, Inc.",
    "GEHC": "GE HealthCare Technologies Inc.",
    "KHC": "The Kraft Heinz Company",
    "DXCM": "DexCom, Inc.",
    "CPRT": "Copart, Inc.",
    "CTSH": "Cognizant Technology Solutions Corporation",
    "VRSK": "Verisk Analytics, Inc.",
    "TEAM": "Atlassian Corporation",
    "INSM": "Insmed Incorporated",
    "ZS": "Zscaler, Inc.",
    "CHTR": "Charter Communications, Inc.",
    "CSGP": "CoStar Group, Inc.",
}


_SP500_DATA = """
MMM|3M
AOS|A. O. Smith
ABT|Abbott Laboratories
ABBV|AbbVie
ACN|Accenture
ADBE|Adobe Inc.
AMD|Advanced Micro Devices
AES|AES Corporation
AFL|Aflac
A|Agilent Technologies
APD|Air Products
ABNB|Airbnb
AKAM|Akamai Technologies
ALB|Albemarle Corporation
ARE|Alexandria Real Estate Equities
ALGN|Align Technology
ALLE|Allegion
LNT|Alliant Energy
ALL|Allstate
GOOGL|Alphabet Inc. (Class A)
GOOG|Alphabet Inc. (Class C)
MO|Altria
AMZN|Amazon
AMCR|Amcor
AEE|Ameren
AEP|American Electric Power
AXP|American Express
AIG|American International Group
AMT|American Tower
AWK|American Water Works
AMP|Ameriprise Financial
AME|Ametek
AMGN|Amgen
APH|Amphenol
ADI|Analog Devices
AON|Aon plc
APA|APA Corporation
APO|Apollo Global Management
AAPL|Apple Inc.
AMAT|Applied Materials
APP|AppLovin
APTV|Aptiv
ACGL|Arch Capital Group
ADM|Archer Daniels Midland
ARES|Ares Management
ANET|Arista Networks
AJG|Arthur J. Gallagher & Co.
AIZ|Assurant
T|AT&T
ATO|Atmos Energy
ADSK|Autodesk
ADP|Automatic Data Processing
AZO|AutoZone
AVB|AvalonBay Communities
AVY|Avery Dennison
AXON|Axon Enterprise
BKR|Baker Hughes
BALL|Ball Corporation
BAC|Bank of America
BAX|Baxter International
BDX|Becton Dickinson
BRK.B|Berkshire Hathaway
BBY|Best Buy
TECH|Bio-Techne
BIIB|Biogen
BLK|BlackRock
BX|Blackstone Inc.
XYZ|Block, Inc.
BNY|BNY Mellon
BA|Boeing
BKNG|Booking Holdings
BSX|Boston Scientific
BMY|Bristol Myers Squibb
AVGO|Broadcom
BR|Broadridge Financial Solutions
BRO|Brown & Brown
BF.B|Brown–Forman
BLDR|Builders FirstSource
BG|Bunge Global
BXP|BXP, Inc.
CHRW|C.H. Robinson
CDNS|Cadence Design Systems
CPT|Camden Property Trust
COF|Capital One
CAH|Cardinal Health
CCL|Carnival Corporation
CARR|Carrier Global
CVNA|Carvana
CASY|Casey's
CAT|Caterpillar Inc.
CBOE|Cboe Global Markets
CBRE|CBRE Group
CDW|CDW Corporation
COR|Cencora
CNC|Centene Corporation
CNP|CenterPoint Energy
CF|CF Industries
CRL|Charles River Laboratories
SCHW|Charles Schwab Corporation
CHTR|Charter Communications
CVX|Chevron Corporation
CMG|Chipotle Mexican Grill
CB|Chubb Limited
CHD|Church & Dwight
CIEN|Ciena
CI|Cigna
CINF|Cincinnati Financial
CTAS|Cintas
CSCO|Cisco
C|Citigroup
CFG|Citizens Financial Group
CLX|Clorox
CME|CME Group
CMS|CMS Energy
KO|Coca-Cola Company (The)
CTSH|Cognizant
COHR|Coherent Corp.
COIN|Coinbase
CL|Colgate-Palmolive
CMCSA|Comcast
FIX|Comfort Systems USA
COP|ConocoPhillips
ED|Consolidated Edison
STZ|Constellation Brands
CEG|Constellation Energy
COO|Cooper Companies (The)
CPRT|Copart
GLW|Corning Inc.
CPAY|Corpay
CTVA|Corteva
CSGP|CoStar Group
COST|Costco
CRH|CRH plc
CRWD|CrowdStrike
CCI|Crown Castle
CSX|CSX Corporation
CMI|Cummins
CVS|CVS Health
DHR|Danaher Corporation
DRI|Darden Restaurants
DDOG|Datadog
DVA|DaVita
DECK|Deckers Brands
DE|Deere & Company
DELL|Dell Technologies
DAL|Delta Air Lines
DVN|Devon Energy
DXCM|Dexcom
FANG|Diamondback Energy
DLR|Digital Realty
DG|Dollar General
DLTR|Dollar Tree
D|Dominion Energy
DPZ|Domino's
DASH|DoorDash
DOV|Dover Corporation
DOW|Dow Inc.
DHI|D. R. Horton
DTE|DTE Energy
DUK|Duke Energy
DD|DuPont
ETN|Eaton Corporation
EBAY|eBay Inc.
ECHO|EchoStar
ECL|Ecolab
EIX|Edison International
EW|Edwards Lifesciences
EA|Electronic Arts
ELV|Elevance Health
EME|Emcor
EMR|Emerson Electric
ETR|Entergy
EOG|EOG Resources
EQT|EQT Corporation
EFX|Equifax
EQIX|Equinix
EQR|Equity Residential
ERIE|Erie Indemnity
ESS|Essex Property Trust
EL|Estée Lauder Companies (The)
EG|Everest Group
EVRG|Evergy
ES|Eversource Energy
EXC|Exelon
EXE|Expand Energy
EXPE|Expedia Group
EXPD|Expeditors International
EXR|Extra Space Storage
XOM|ExxonMobil
FFIV|F5, Inc.
FDS|FactSet
FICO|Fair Isaac
FAST|Fastenal
FRT|Federal Realty Investment Trust
FDX|FedEx
FDXF|FedEx Freight
FIS|Fidelity National Information Services
FITB|Fifth Third Bancorp
FSLR|First Solar
FE|FirstEnergy
FISV|Fiserv
FLEX|Flex Ltd.
F|Ford Motor Company
FTNT|Fortinet
FTV|Fortive
FOXA|Fox Corporation (Class A)
FOX|Fox Corporation (Class B)
BEN|Franklin Resources
FCX|Freeport-McMoRan
GRMN|Garmin
IT|Gartner
GE|GE Aerospace
GEHC|GE HealthCare
GEV|GE Vernova
GEN|Gen Digital
GNRC|Generac
GD|General Dynamics
GIS|General Mills
GM|General Motors
GPC|Genuine Parts Company
GILD|Gilead Sciences
GPN|Global Payments
GL|Globe Life
GDDY|GoDaddy
GS|Goldman Sachs
HAL|Halliburton
HIG|Hartford (The)
HAS|Hasbro
HCA|HCA Healthcare
DOC|Healthpeak Properties
HSIC|Henry Schein
HSY|Hershey Company (The)
HPE|Hewlett Packard Enterprise
HLT|Hilton Worldwide
HD|Home Depot (The)
HONA|Honeywell Aerospace
HON|Honeywell Technologies
HRL|Hormel Foods
HST|Host Hotels & Resorts
HWM|Howmet Aerospace
HPQ|HP Inc.
HUBB|Hubbell Incorporated
HUM|Humana
HBAN|Huntington Bancshares
HII|Huntington Ingalls Industries
IBM|IBM
IEX|IDEX Corporation
IDXX|Idexx Laboratories
ITW|Illinois Tool Works
INCY|Incyte
IR|Ingersoll Rand
PODD|Insulet Corporation
INTC|Intel
IBKR|Interactive Brokers
ICE|Intercontinental Exchange
IFF|International Flavors & Fragrances
IP|International Paper
INTU|Intuit
ISRG|Intuitive Surgical
IVZ|Invesco
INVH|Invitation Homes
IQV|IQVIA
IRM|Iron Mountain
JBHT|J.B. Hunt
JBL|Jabil
JKHY|Jack Henry & Associates
J|Jacobs Solutions
JNJ|Johnson & Johnson
JCI|Johnson Controls
JPM|JPMorgan Chase
KVUE|Kenvue
KDP|Keurig Dr Pepper
KEY|KeyCorp
KEYS|Keysight Technologies
KMB|Kimberly-Clark
KIM|Kimco Realty
KMI|Kinder Morgan
KKR|KKR & Co.
KLAC|KLA Corporation
KHC|Kraft Heinz
KR|Kroger
LHX|L3Harris
LH|Labcorp
LRCX|Lam Research
LVS|Las Vegas Sands
LDOS|Leidos
LEN|Lennar
LII|Lennox International
LLY|Lilly (Eli)
LIN|Linde plc
LYV|Live Nation Entertainment
LMT|Lockheed Martin
L|Loews Corporation
LOW|Lowe's
LULU|Lululemon Athletica
LITE|Lumentum
LYB|LyondellBasell
MTB|M&T Bank
MPC|Marathon Petroleum
MAR|Marriott International
MRSH|Marsh McLennan
MLM|Martin Marietta Materials
MRVL|Marvell Technology
MAS|Masco
MA|Mastercard
MKC|McCormick & Company
MCD|McDonald's
MCK|McKesson Corporation
MDT|Medtronic
MRK|Merck & Co.
META|Meta Platforms
MET|MetLife
MTD|Mettler Toledo
MGM|MGM Resorts
MCHP|Microchip Technology
MU|Micron Technology
MSFT|Microsoft
MAA|Mid-America Apartment Communities
MRNA|Moderna
TAP|Molson Coors Beverage Company
MDLZ|Mondelez International
MPWR|Monolithic Power Systems
MNST|Monster Beverage
MCO|Moody's Corporation
MS|Morgan Stanley
MOS|Mosaic Company (The)
MSI|Motorola Solutions
MSCI|MSCI Inc.
NDAQ|Nasdaq, Inc.
NTAP|NetApp
NFLX|Netflix
NEM|Newmont
NWSA|News Corp (Class A)
NWS|News Corp (Class B)
NEE|NextEra Energy
NKE|Nike, Inc.
NI|NiSource
NDSN|Nordson Corporation
NSC|Norfolk Southern
NTRS|Northern Trust
NOC|Northrop Grumman
NCLH|Norwegian Cruise Line Holdings
NRG|NRG Energy
NUE|Nucor
NVDA|Nvidia
NVR|NVR, Inc.
NXPI|NXP Semiconductors
ORLY|O’Reilly Automotive
OXY|Occidental Petroleum
ODFL|Old Dominion
OMC|Omnicom Group
ON|ON Semiconductor
OKE|Oneok
ORCL|Oracle Corporation
OTIS|Otis Worldwide
PCAR|Paccar
PKG|Packaging Corporation of America
PLTR|Palantir Technologies
PANW|Palo Alto Networks
PSKY|Paramount Skydance Corporation
PH|Parker Hannifin
PAYX|Paychex
PYPL|PayPal
PNR|Pentair
PEP|PepsiCo
PFE|Pfizer
PCG|PG&E Corporation
PM|Philip Morris International
PSX|Phillips 66
PNW|Pinnacle West Capital
PNC|PNC Financial Services
PPG|PPG Industries
PPL|PPL Corporation
PFG|Principal Financial Group
PG|Procter & Gamble
PGR|Progressive Corporation
PLD|Prologis
PRU|Prudential Financial
PEG|Public Service Enterprise Group
PTC|PTC Inc.
PSA|Public Storage
PHM|PulteGroup
PWR|Quanta Services
QCOM|Qualcomm
QQQ|Invesco QQQ Trust
DGX|Quest Diagnostics
Q|Qnity Electronics
RL|Ralph Lauren Corporation
RJF|Raymond James Financial
RTX|RTX Corporation
O|Realty Income
REG|Regency Centers
REGN|Regeneron Pharmaceuticals
RF|Regions Financial Corporation
RSG|Republic Services
RMD|ResMed
RVTY|Revvity
HOOD|Robinhood Markets
ROK|Rockwell Automation
ROL|Rollins, Inc.
ROP|Roper Technologies
ROST|Ross Stores
RCL|Royal Caribbean Group
SPGI|S&P Global
SPY|SPDR S&P 500 ETF Trust
CRM|Salesforce
SNDK|Sandisk
SBAC|SBA Communications
SLB|Schlumberger
STX|Seagate Technology
SRE|Sempra
NOW|ServiceNow
SHW|Sherwin-Williams
SPG|Simon Property Group
SWKS|Skyworks Solutions
SJM|J.M. Smucker Company (The)
SW|Smurfit Westrock
SNA|Snap-on
SOLV|Solventum
SO|Southern Company
LUV|Southwest Airlines
SWK|Stanley Black & Decker
SBUX|Starbucks
STT|State Street Corporation
STLD|Steel Dynamics
STE|Steris
SYK|Stryker Corporation
SMCI|Supermicro
SYF|Synchrony Financial
SNPS|Synopsys
SYY|Sysco
TMUS|T-Mobile US
TROW|T. Rowe Price
TTWO|Take-Two Interactive
TPR|Tapestry, Inc.
TRGP|Targa Resources
TGT|Target Corporation
TEL|TE Connectivity
TDY|Teledyne Technologies
TER|Teradyne
TSLA|Tesla, Inc.
TXN|Texas Instruments
TPL|Texas Pacific Land Corporation
TXT|Textron
TMO|Thermo Fisher Scientific
TJX|TJX Companies
TKO|TKO Group Holdings
TTD|Trade Desk (The)
TSCO|Tractor Supply
TT|Trane Technologies
TDG|TransDigm Group
TRV|Travelers Companies (The)
TRMB|Trimble Inc.
TFC|Truist Financial
TYL|Tyler Technologies
TSN|Tyson Foods
USB|U.S. Bancorp
UBER|Uber
UDR|UDR, Inc.
ULTA|Ulta Beauty
UNP|Union Pacific Corporation
UAL|United Airlines Holdings
UPS|United Parcel Service
URI|United Rentals
UNH|UnitedHealth Group
UHS|Universal Health Services
VLO|Valero Energy
VEEV|Veeva Systems
VTR|Ventas
VLTO|Veralto
VRSN|Verisign
VRSK|Verisk Analytics
VZ|Verizon
VRTX|Vertex Pharmaceuticals
VRT|Vertiv
VTRS|Viatris
VICI|Vici Properties
V|Visa Inc.
VST|Vistra Corp.
VMC|Vulcan Materials Company
WRB|W. R. Berkley Corporation
GWW|W. W. Grainger
WAB|Wabtec
WMT|Walmart
DIS|Walt Disney Company (The)
WBD|Warner Bros. Discovery
WM|Waste Management
WAT|Waters Corporation
WEC|WEC Energy Group
WFC|Wells Fargo
WELL|Welltower
WST|West Pharmaceutical Services
WDC|Western Digital
WY|Weyerhaeuser
WSM|Williams-Sonoma, Inc.
WMB|Williams Companies
WTW|Willis Towers Watson
WDAY|Workday, Inc.
WYNN|Wynn Resorts
XEL|Xcel Energy
XYL|Xylem Inc.
YUM|Yum! Brands
ZBRA|Zebra Technologies
ZBH|Zimmer Biomet
ZTS|Zoetis
"""
SP500_STOCK_INDEX = dict(line.split("|", 1) for line in _SP500_DATA.splitlines() if line)

_CSI300_DATA = """
000001.SZ|平安银行
000002.SZ|万科A
000063.SZ|中兴通讯
000100.SZ|TCL科技
000157.SZ|中联重科
000166.SZ|申万宏源
000301.SZ|东方盛虹
000333.SZ|美的集团
000338.SZ|潍柴动力
000408.SZ|藏格矿业
000425.SZ|徐工机械
000538.SZ|云南白药
000568.SZ|泸州老窖
000596.SZ|古井贡酒
000617.SZ|中油资本
000625.SZ|长安汽车
000630.SZ|铜陵有色
000651.SZ|格力电器
000657.SZ|中钨高新
000708.SZ|中信特钢
000725.SZ|京东方A
000768.SZ|中航西飞
000776.SZ|广发证券
000792.SZ|盐湖股份
000807.SZ|云铝股份
000858.SZ|五 粮 液
000895.SZ|双汇发展
000938.SZ|紫光股份
000963.SZ|华东医药
000975.SZ|山金国际
000977.SZ|浪潮信息
000988.SZ|华工科技
000999.SZ|华润三九
001280.SZ|中国铀业
001391.SZ|国货航
001965.SZ|招商公路
001979.SZ|招商蛇口
002001.SZ|新和成
002027.SZ|分众传媒
002028.SZ|思源电气
002049.SZ|紫光国微
002050.SZ|三花智控
002074.SZ|国轩高科
002142.SZ|宁波银行
002179.SZ|中航光电
002202.SZ|金风科技
002230.SZ|科大讯飞
002236.SZ|大华股份
002241.SZ|歌尔股份
002304.SZ|洋河股份
002311.SZ|海大集团
002352.SZ|顺丰控股
002353.SZ|杰瑞股份
002371.SZ|北方华创
002384.SZ|东山精密
002415.SZ|海康威视
002422.SZ|科伦药业
002460.SZ|赣锋锂业
002463.SZ|沪电股份
002466.SZ|天齐锂业
002475.SZ|立讯精密
002493.SZ|荣盛石化
002532.SZ|天山铝业
002558.SZ|巨人网络
002594.SZ|比亚迪
002600.SZ|领益智造
002602.SZ|世纪华通
002625.SZ|光启技术
002648.SZ|卫星化学
002709.SZ|天赐材料
002714.SZ|牧原股份
002736.SZ|国信证券
002837.SZ|英维克
002916.SZ|深南电路
002920.SZ|德赛西威
002938.SZ|鹏鼎控股
003816.SZ|中国广核
159915.SZ|创业板ETF
300014.SZ|亿纬锂能
300015.SZ|爱尔眼科
300033.SZ|同花顺
300059.SZ|东方财富
300122.SZ|智飞生物
300124.SZ|汇川技术
300251.SZ|光线传媒
300274.SZ|阳光电源
300308.SZ|中际旭创
300316.SZ|晶盛机电
300394.SZ|天孚通信
300408.SZ|三环集团
300413.SZ|芒果超媒
300418.SZ|昆仑万维
300433.SZ|蓝思科技
300442.SZ|润泽科技
300450.SZ|先导智能
300476.SZ|胜宏科技
300498.SZ|温氏股份
300502.SZ|新易盛
300628.SZ|亿联网络
300661.SZ|圣邦股份
300750.SZ|宁德时代
300760.SZ|迈瑞医疗
300803.SZ|指南针
300832.SZ|新产业
300866.SZ|安克创新
300896.SZ|爱美客
300999.SZ|金龙鱼
301165.SZ|锐捷网络
301236.SZ|软通动力
301269.SZ|华大九天
301308.SZ|江波龙
302132.SZ|中航成飞
600000.SH|浦发银行
600009.SH|上海机场
600010.SH|包钢股份
600011.SH|华能国际
600015.SH|华夏银行
600016.SH|民生银行
600018.SH|上港集团
510300.SH|沪深300ETF
600019.SH|宝钢股份
600023.SH|浙能电力
600025.SH|华能水电
600026.SH|中远海能
600027.SH|华电国际
600028.SH|中国石化
600029.SH|南方航空
600030.SH|中信证券
600031.SH|三一重工
600036.SH|招商银行
600039.SH|四川路桥
600048.SH|保利发展
600050.SH|中国联通
600061.SH|国投资本
600066.SH|宇通客车
600085.SH|同仁堂
600089.SH|特变电工
600104.SH|上汽集团
600111.SH|北方稀土
600115.SH|中国东航
600118.SH|中国卫星
600150.SH|中国船舶
600160.SH|巨化股份
600176.SH|中国巨石
600183.SH|生益科技
600188.SH|兖矿能源
600196.SH|复星医药
600219.SH|南山铝业
600221.SH|海航控股
600233.SH|圆通速递
600276.SH|恒瑞医药
600309.SH|万华化学
600346.SH|恒力石化
600362.SH|江西铜业
600372.SH|中航机载
600406.SH|国电南瑞
600415.SH|小商品城
600426.SH|华鲁恒升
600436.SH|片仔癀
600438.SH|通威股份
600460.SH|士兰微
600482.SH|中国动力
600489.SH|中金黄金
600515.SH|海南机场
600519.SH|贵州茅台
600522.SH|中天科技
600547.SH|山东黄金
600549.SH|厦门钨业
600570.SH|恒生电子
600584.SH|长电科技
600585.SH|海螺水泥
600588.SH|用友网络
600600.SH|青岛啤酒
600660.SH|福耀玻璃
600674.SH|川投能源
600690.SH|海尔智家
600741.SH|华域汽车
600760.SH|中航沈飞
600795.SH|国电电力
600803.SH|新奥股份
600809.SH|山西汾酒
600845.SH|宝信软件
600875.SH|东方电气
600886.SH|国投电力
600887.SH|伊利股份
600893.SH|航发动力
600900.SH|长江电力
600905.SH|三峡能源
600918.SH|中泰证券
600919.SH|江苏银行
600926.SH|杭州银行
600930.SH|华电新能
600938.SH|中国海油
600941.SH|中国移动
600958.SH|东方证券
600989.SH|宝丰能源
600999.SH|招商证券
601006.SH|大秦铁路
601009.SH|南京银行
601012.SH|隆基绿能
601018.SH|宁波港
601021.SH|春秋航空
601058.SH|赛轮轮胎
601059.SH|信达证券
601066.SH|中信建投
601077.SH|渝农商行
601088.SH|中国神华
601100.SH|恒立液压
601111.SH|中国国航
601117.SH|中国化学
601127.SH|赛力斯
601136.SH|首创证券
601138.SH|工业富联
601166.SH|兴业银行
601169.SH|北京银行
601186.SH|中国铁建
601211.SH|国泰海通
601225.SH|陕西煤业
601229.SH|上海银行
601238.SH|广汽集团
601288.SH|农业银行
601318.SH|中国平安
601319.SH|中国人保
601328.SH|交通银行
601336.SH|新华保险
601360.SH|三六零
601377.SH|兴业证券
601390.SH|中国中铁
601398.SH|工商银行
601456.SH|国联民生
601600.SH|中国铝业
601601.SH|中国太保
601607.SH|上海医药
601618.SH|中国中冶
601628.SH|中国人寿
601633.SH|长城汽车
601658.SH|邮储银行
601668.SH|中国建筑
601669.SH|中国电建
601688.SH|华泰证券
601689.SH|拓普集团
601698.SH|中国卫通
601727.SH|上海电气
601728.SH|中国电信
601766.SH|中国中车
601788.SH|光大证券
601800.SH|中国交建
601816.SH|京沪高铁
601818.SH|光大银行
601825.SH|沪农商行
601838.SH|成都银行
601857.SH|中国石油
601868.SH|中国能建
601872.SH|招商轮船
601877.SH|正泰电器
601878.SH|浙商证券
601881.SH|中国银河
601888.SH|中国中免
601898.SH|中煤能源
601899.SH|紫金矿业
601901.SH|方正证券
601916.SH|浙商银行
601919.SH|中远海控
601939.SH|建设银行
601985.SH|中国核电
601988.SH|中国银行
601995.SH|中金公司
601998.SH|中信银行
603019.SH|中科曙光
603259.SH|药明康德
603260.SH|合盛硅业
603288.SH|海天味业
603296.SH|华勤技术
603369.SH|今世缘
603392.SH|万泰生物
603501.SH|豪威集团
603799.SH|华友钴业
603893.SH|瑞芯微
603986.SH|兆易创新
603993.SH|洛阳钼业
605117.SH|德业股份
605499.SH|东鹏饮料
688008.SH|澜起科技
688009.SH|中国通号
688012.SH|中微公司
688036.SH|传音控股
688041.SH|海光信息
688047.SH|龙芯中科
688072.SH|拓荆科技
688082.SH|盛美上海
688111.SH|金山办公
688126.SH|沪硅产业
688183.SH|生益电子
688223.SH|晶科能源
688256.SH|寒武纪
688271.SH|联影医疗
688303.SH|大全能源
688396.SH|华润微
688472.SH|阿特斯
688506.SH|百利天恒
688521.SH|芯原股份
688981.SH|中芯国际
"""
CSI300_STOCK_INDEX = dict(line.split("|", 1) for line in _CSI300_DATA.splitlines() if line)

__all__ = ["CSI300_STOCK_INDEX", "NASDAQ100_STOCK_INDEX", "SP500_STOCK_INDEX"]

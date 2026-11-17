#!/usr/bin/env python3
"""Generate the mock data layer for the Jev exposure-review project.

Outputs:
  data/raw/users.csv
  data/raw/items.csv
  data/raw/promo_rules.json
  data/raw/compliance_lexicon.txt
  data/raw/lexicon_variants.tsv
  data/raw/history_reason_stats.csv
  data/raw/city_climate.json
  data/mock.db

Design notes:
  * 200 users / 200 items, all fictional, no PII.
  * Scenario date is 2026-06-15 so the Hangzhou "梅雨季" context is coherent.
  * List fields are pipe-separated in CSV and JSON arrays in SQLite.
  * Every item has at least one attribute that can support or refute a claim.
  * Brands are invented; any resemblance to real brands is accidental.
"""

from __future__ import annotations

import csv
import json
import random
import sqlite3
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "mock.db"
SCENARIO_DATE = date(2026, 6, 15)
RNG = random.Random(20260615)

RAW.mkdir(parents=True, exist_ok=True)

BRANDS = [
    "栖物", "简序", "拾光", "山止", "有为", "轻野", "小满", "知竹",
    "鹿鸣", "青柚", "沐言", "素造", "云栖", "南栀", "北岸", "一木",
    "良屿", "食光", "麦田", "果然", "清欢", "暖山", "步履", "风行",
    "极简", "星野", "智造", "微光", "小鲸", "芽米", "童屿", "康屿",
    "本初", "元气", "森屿", "岚山", "溪木", "望舒", "砚白", "竹里",
]


def T(
    key, l1, l2, l3, brand, base, specs, functions, material,
    audience, season, price, claims=None, quals=None,
    regulated="general", sensitive=False, note="",
):
    return {
        "key": key, "l1": l1, "l2": l2, "l3": l3, "brand": brand,
        "base": base, "specs": specs, "functions": functions,
        "material": material, "audience": audience, "season": season,
        "price": price, "claims": claims or [], "quals": quals or ["无"],
        "regulated": regulated, "sensitive": sensitive, "note": note,
    }


TYPES = [
    T("home_box", "家居日用", "收纳整理", "收纳盒", "栖物", "可折叠防尘收纳盒",
      ["35L 奶油白", "55L 雾霾蓝", "70L 透明", "24L 窄缝款", "45L 带轮"],
      ["折叠", "防尘", "收纳"], "PP", "租房人群", "全季", (2990, 6990),
      note="普通家居用品；不得宣称除湿、杀菌等功效"),
    T("home_tissue", "家居日用", "清洁用品", "抽纸", "简序", "原生木浆抽纸",
      ["3层100抽×24包", "4层90抽×18包", "3层120抽×16包", "便携装 10包", "家庭装 30包"],
      ["清洁", "吸水"], "原生木浆", "家庭", "全季", (2990, 5990),
      note="普通日用品；避免绝对化用语"),
    T("home_bedding", "家居日用", "床上用品", "四件套", "拾光", "纯棉四件套",
      ["100支 1.8m床", "60支 1.5m床", "水洗棉 1.2m床", "磨毛 2.0m床", "天丝 1.8m床"],
      ["亲肤", "透气"], "长绒棉", "家庭", "四季", (19900, 49900),
      note="普通家纺；不得宣称抗菌、防螨等未证实功效"),
    T("home_pan", "家居日用", "厨房用具", "不粘锅", "山止", "麦饭石不粘炒锅",
      ["28cm 平底", "30cm 深型", "32cm 带盖", "26cm 轻量", "34cm 家用"],
      ["不粘", "少油烟"], "铝合金", "下厨人群", "全季", (8900, 25900),
      note="普通厨具；不得宣称无油烟、健康无害等绝对表述"),
    T("home_fragrance", "家居日用", "香薰家纺", "香薰", "有为", "无火香薰礼盒",
      ["白茶 200ml", "雪松 150ml", "柑橘 300ml", "栀子花 100ml", "木质调 250ml"],
      ["扩香", "除味"], "植物精油", "品质人群", "全季", (5900, 16900),
      note="普通香薰；不得宣称助眠、杀菌等功效"),

    T("beauty_cleanser", "美妆个护", "面部护肤", "洁面乳", "轻野", "氨基酸洁面乳",
      ["120g 温和型", "100g 控油型", "150g 敏感肌", "80g 旅行装", "120g 泡沫型"],
      ["清洁", "保湿"], "氨基酸表活", "敏感肌", "全季", (3900, 9900),
      ["清洁", "保湿"], ["妆字号"], "cosmetic", True,
      "普通化妆品；不得宣称医疗、药用、美白祛斑等特殊功效"),
    T("beauty_cream", "美妆个护", "面部护肤", "面霜", "小满", "神经酰胺保湿面霜",
      ["50g 清爽型", "50g 滋润型", "30g 修护型", "80g 家庭装", "15g 试用装"],
      ["保湿", "修护"], "神经酰胺", "干皮人群", "冬季", (5900, 19900),
      ["保湿", "修护"], ["妆字号"], "cosmetic", True,
      "普通化妆品；修护宣称不得超出备案范围"),
    T("beauty_lipstick", "美妆个护", "彩妆", "口红", "知竹", "丝绒哑光口红",
      ["#01 豆沙", "#02 正红", "#03 枫叶", "#04 奶茶", "#05 莓果"],
      ["显色", "持久"], "植物蜡", "通勤女性", "全季", (6900, 16900),
      ["显色", "持久"], ["妆字号"], "cosmetic", True,
      "普通化妆品；不得宣称可食用、食品级"),
    T("beauty_shampoo", "美妆个护", "洗发护发", "洗发水", "鹿鸣", "控油蓬松洗发水",
      ["500ml 无硅油", "400ml 去屑型", "750ml 家庭装", "300ml 旅行装", "500ml 香氛型"],
      ["清洁", "控油"], "氨基酸表活", "油头人群", "全季", (3900, 12900),
      ["清洁", "控油"], ["妆字号"], "cosmetic", True,
      "普通化妆品；去屑、防脱需特证或备案支撑"),
    T("beauty_lotion", "美妆个护", "身体护理", "身体乳", "青柚", "烟酰胺身体乳",
      ["250ml 清爽", "400ml 滋润", "300ml 香氛", "200ml 便携", "500ml 家庭装"],
      ["保湿", "滋润"], "烟酰胺", "干皮人群", "冬季", (4900, 12900),
      ["保湿", "滋润"], ["妆字号"], "cosmetic", True,
      "普通化妆品；美白宣称需特殊化妆品注册"),

    T("food_nuts", "食品生鲜", "零食", "每日坚果", "沐言", "每日坚果混合装",
      ["30袋 750g", "20袋 500g", "14袋 350g", "礼盒装 30袋", "家庭装 45袋"],
      ["充饥", "补充能量"], "混合坚果", "办公室人群", "全季", (4990, 12900),
      [], ["SC"], "food", False, "普通食品；不得宣称保健、治疗功效"),
    T("food_coffee", "食品生鲜", "饮料", "咖啡液", "素造", "冷萃咖啡液",
      ["10条 意式", "20条 美式", "14条 生椰", "30条 混合", "7条 尝鲜"],
      ["提神"], "咖啡豆", "上班族", "全季", (3990, 9900),
      [], ["SC"], "food", False, "普通食品；不得宣称提神醒脑等保健功效"),
    T("food_rice", "食品生鲜", "粮油", "大米", "云栖", "五常大米",
      ["5kg 真空装", "10kg 家庭装", "2.5kg 小包装", "5kg 礼盒", "1kg 尝鲜"],
      ["主食"], "稻米", "家庭", "全季", (3990, 11900),
      [], ["SC"], "food", False, "普通食品；不得宣称有机、绿色等未认证资质"),
    T("food_blueberry", "食品生鲜", "生鲜", "蓝莓", "南栀", "云南蓝莓",
      ["125g×4盒", "500g 大果", "1kg 家庭装", "125g×8盒", "250g 礼盒"],
      ["水果"], "蓝莓", "家庭", "夏季", (3990, 9900),
      [], ["SC"], "food", False, "普通食品；不得宣称护眼、抗氧化等功效"),
    T("food_yogurt", "食品生鲜", "乳品", "酸奶", "北岸", "低温酸奶",
      ["200g×6杯", "100g×12杯", "1kg 桶装", "200g×10杯", "150g×8杯"],
      ["乳制品"], "生牛乳", "家庭", "全季", (2990, 7900),
      [], ["SC"], "food", False, "普通食品；不得宣称调节肠道菌群等功效"),

    T("wear_sunshirt", "服饰鞋包", "女装", "防晒衣", "一木", "轻薄防晒衣",
      ["女款 白色 M", "女款 浅蓝 L", "男款 灰色 XL", "情侣款 米白", "加大码 黑色"],
      ["防晒", "透气"], "锦纶", "通勤人群", "夏季", (8900, 19900),
      note="普通服饰；防晒宣称需符合 UPF 标准并提供检测依据"),
    T("wear_pants", "服饰鞋包", "女装", "阔腿裤", "良屿", "垂感阔腿裤",
      ["黑色 S", "卡其 M", "藏青 L", "米白 XL", "灰色 加长"],
      ["垂感", "显瘦"], "聚酯纤维", "通勤女性", "四季", (9900, 19900),
      note="普通服饰；避免绝对化身材表述"),
    T("wear_shoes", "服饰鞋包", "鞋靴", "跑鞋", "食光", "轻量缓震跑鞋",
      ["黑白 38", "灰橙 40", "米白 42", "全黑 44", "粉白 36"],
      ["缓震", "回弹"], "网布", "跑步人群", "全季", (15900, 39900),
      note="普通鞋类；不得宣称治疗足部疾病"),
    T("wear_bag", "服饰鞋包", "箱包", "托特包", "麦田", "大容量托特包",
      ["黑色 通勤", "棕色 复古", "米白 大号", "帆布 条纹", "皮质 小号"],
      ["大容量", "通勤"], "PU", "通勤人群", "全季", (8900, 29900),
      note="普通箱包；材质宣称需与标注一致"),
    T("wear_bra", "服饰鞋包", "内衣", "内衣", "果然", "无痕舒适内衣",
      ["肤色 M", "黑色 L", "浅粉 S", "灰蓝 XL", "组合装 3件"],
      ["无痕", "舒适"], "氨纶", "女性", "全季", (6900, 16900),
      note="普通服饰；不得宣称丰胸、塑形医疗效果"),

    T("tech_powerbank", "3C数码", "手机配件", "充电宝", "清欢", "自带线快充充电宝",
      ["10000mAh 白", "20000mAh 黑", "5000mAh 迷你", "10000mAh 蓝", "20000mAh 带屏"],
      ["充电", "便携"], "锂聚合物", "通勤人群", "全季", (7900, 19900),
      note="3C 配件；容量与快充协议需与检测报告一致"),
    T("tech_earphone", "3C数码", "耳机", "蓝牙耳机", "暖山", "入耳式降噪蓝牙耳机",
      ["白色 标准版", "黑色 Pro", "米色 轻量", "蓝色 运动版", "紫色 礼盒"],
      ["降噪", "通话"], "ABS", "通勤人群", "全季", (9900, 39900),
      note="3C 配件；降噪深度需有检测依据"),
    T("tech_band", "3C数码", "智能穿戴", "智能手环", "步履", "多功能智能手环",
      ["黑色 标准", "粉色 轻享", "蓝色 运动", "银色 商务", "红色 联名"],
      ["计步", "心率", "睡眠监测"], "TPU", "运动人群", "全季", (12900, 29900),
      note="3C 穿戴；健康数据仅供参考，不得宣称医疗诊断"),
    T("tech_keyboard", "3C数码", "电脑外设", "机械键盘", "风行", "热插拔机械键盘",
      ["87键 青轴", "104键 红轴", "75键 茶轴", "68键 白轴", "87键 静音"],
      ["输入"], "PBT", "办公人群", "全季", (15900, 49900),
      note="3C 外设；避免绝对化手感表述"),
    T("tech_fan", "3C数码", "小家电", "桌面风扇", "极简", "静音桌面风扇",
      ["白色 小号", "绿色 中号", "粉色 充电款", "灰色 摇头款", "蓝色 挂脖款"],
      ["送风", "降温"], "ABS", "办公人群", "夏季", (4900, 12900),
      note="小家电；不得宣称空调级制冷"),

    T("baby_diaper", "母婴亲子", "纸尿裤", "纸尿裤", "星野", "超薄透气纸尿裤",
      ["L码 64片", "M码 72片", "XL码 56片", "S码 80片", "拉拉裤 L码 60片"],
      ["吸水", "透气"], "无纺布", "婴幼儿", "全季", (8900, 19900),
      [], ["GB15979"], "children", True,
      "婴幼儿用品；不得宣称治疗红臀、湿疹等功效"),
    T("baby_wipes", "母婴亲子", "婴童洗护", "婴儿湿巾", "智造", "婴儿手口湿巾",
      ["80抽×6包", "100抽×3包", "20抽×10包", "80抽×12包", "便携 10抽×20"],
      ["清洁"], "水刺无纺布", "婴幼儿", "全季", (2990, 7900),
      [], ["GB15979"], "children", True,
      "婴幼儿用品；不得宣称杀菌、消毒等医疗功效"),
    T("baby_blocks", "母婴亲子", "玩具", "积木", "微光", "大颗粒益智积木",
      ["120粒 收纳桶", "200粒 豪华版", "80粒 入门", "160粒 城市系列", "240粒 动物园"],
      ["拼搭", "益智"], "ABS", "儿童", "全季", (5900, 19900),
      [], ["3C"], "children", True,
      "儿童玩具；需标注适用年龄，不得宣称开发智力等效果"),
    T("baby_tee", "母婴亲子", "童装", "童装T恤", "小鲸", "纯棉儿童短袖T恤",
      ["100cm 白色", "110cm 黄色", "120cm 蓝色", "130cm 粉色", "140cm 灰色"],
      ["亲肤", "透气"], "纯棉", "儿童", "夏季", (3900, 9900),
      [], ["GB31701"], "children", True,
      "儿童服饰；需符合 A 类标准，避免绝对化安全表述"),
    T("baby_bottle", "母婴亲子", "喂养", "奶瓶", "芽米", "宽口径防胀气奶瓶",
      ["240ml 玻璃", "160ml PPSU", "300ml 带手柄", "240ml 硅胶", "180ml 新生儿"],
      ["喂养", "防胀气"], "PPSU", "婴幼儿", "全季", (5900, 15900),
      [], ["GB4806"], "children", True,
      "婴幼儿用品；材质需符合食品接触标准"),

    T("sport_mat", "运动户外", "健身器材", "瑜伽垫", "童屿", "加厚防滑瑜伽垫",
      ["183×61cm 紫", "183×61cm 绿", "185×68cm 灰", "10mm 加厚 蓝", "5mm 旅行款"],
      ["防滑", "缓冲"], "TPE", "健身人群", "全季", (4900, 12900),
      note="普通运动器材；不得宣称矫正体态等医疗功效"),
    T("sport_dumbbell", "运动户外", "健身器材", "哑铃", "康屿", "可调节哑铃",
      ["10kg 一对", "15kg 一对", "20kg 一对", "5kg 单只", "24kg 一对"],
      ["力量训练"], "铸铁", "健身人群", "全季", (8900, 29900),
      note="普通运动器材；注意承重与安全提示"),
    T("sport_chair", "运动户外", "户外装备", "露营椅", "本初", "便携折叠露营椅",
      ["卡其 标准", "黑色 加宽", "军绿 高背", "灰色 轻量", "蓝色 儿童款"],
      ["折叠", "承重"], "铝合金", "户外人群", "夏季", (6900, 19900),
      note="普通户外用品；承重宣称需有测试依据"),
    T("sport_tee", "运动户外", "运动服饰", "速干T恤", "元气", "速干运动T恤",
      ["男款 黑 L", "女款 白 M", "男款 灰 XL", "女款 粉 S", "情侣款 蓝"],
      ["速干", "透气"], "聚酯纤维", "运动人群", "夏季", (4900, 12900),
      note="普通运动服饰；速干性能需有检测依据"),
    T("sport_knee", "运动户外", "护具", "护膝", "森屿", "运动防护护膝",
      ["单只 黑色 M", "一对 灰色 L", "加压款 蓝色", "保暖款 肤色", "儿童款 粉色"],
      ["支撑", "防护"], "锦纶", "运动人群", "全季", (3900, 9900),
      note="普通护具；不得宣称治疗关节炎等医疗功效"),

    T("health_vc", "保健医疗", "营养补充", "维生素C", "岚山", "维生素C咀嚼片",
      ["100片 橙味", "60片 无糖", "120片 家庭装", "30片 便携", "100片 柠檬味"],
      ["补充维生素C"], "维生素C", "中老年", "全季", (5900, 15900),
      ["补充维生素C"], ["蓝帽子"], "health_food", True,
      "保健食品；不得替代药物，宣称不得超出批准范围"),
    T("health_protein", "保健医疗", "营养补充", "蛋白粉", "溪木", "乳清蛋白粉",
      ["1kg 香草", "750g 巧克力", "2kg 原味", "500g 试用", "1kg 分离乳清"],
      ["补充蛋白质"], "乳清蛋白", "健身人群", "全季", (12900, 29900),
      ["补充蛋白质"], ["SC"], "food", False,
      "普通食品；不得宣称增肌、减脂等保健功效"),
    T("health_bp", "保健医疗", "医疗器械", "血压计", "望舒", "臂式电子血压计",
      ["标准版 白", "语音版 灰", "充电款 黑", "大屏版 白", "双人记忆 灰"],
      ["测量血压"], "ABS", "中老年", "全季", (15900, 39900),
      ["测量血压"], ["械字号"], "medical_device", True,
      "医疗器械；需按注册证适用范围宣称，不得夸大疗效"),
    T("health_neck", "保健医疗", "医疗器械", "颈椎牵引器", "砚白", "家用颈椎牵引器",
      ["基础款 灰", "充气款 蓝", "便携款 黑", "加强款 灰", "旅行装 蓝"],
      ["牵引", "支撑"], "TPU", "中老年", "全季", (8900, 25900),
      ["牵引", "支撑"], ["械字号"], "medical_device", True,
      "医疗器械；不得宣称治愈颈椎病"),
    T("health_eyemask", "保健医疗", "护理器械", "蒸汽眼罩", "竹里", "恒温蒸汽眼罩",
      ["10片 无香", "20片 薰衣草", "5片 洋甘菊", "30片 混合", "12片 玫瑰"],
      ["热敷", "放松"], "无纺布", "办公人群", "全季", (2990, 7900),
      ["热敷", "放松"], ["无"], "general", False,
      "普通日用品；不得宣称治疗干眼症、近视等"),
]

assert len(TYPES) == 40, len(TYPES)
assert all(len(t["specs"]) == 5 for t in TYPES)


def money_in_range(low: int, high: int) -> int:
    """Price ending in .9, inside [low, high] cents."""
    lo = max(low // 100, 1)
    hi = max(high // 100, lo)
    value = RNG.randint(lo, hi) * 100 - 10
    return max(low, min(high, value))


def original_price(price: int) -> int:
    raw = int(price * RNG.uniform(1.25, 1.8))
    rounded = max(price + 500, (raw // 100) * 100 - 10)
    return rounded


def gen_items():
    items = []
    n = 0
    for t in TYPES:
        for spec in t["specs"]:
            n += 1
            item_id = f"i_{n:04d}"
            price = money_in_range(*t["price"])
            title = f"{t['brand']} {t['base']} {spec}"
            items.append({
                "item_id": item_id,
                "title": title,
                "brand": t["brand"],
                "category_l1": t["l1"],
                "category_l2": t["l2"],
                "category_l3": t["l3"],
                "functions": t["functions"],
                "material": t["material"],
                "spec": spec,
                "suit_audience": t["audience"],
                "suit_season": t["season"],
                "efficacy_claims_allowed": t["claims"],
                "qualifications": t["quals"],
                "price_cents": price,
                "original_price_cents": original_price(price),
                "promo_tags": [],
                "promo_rule_ids": [],
                "stock": RNG.choice([0, RNG.randint(20, 2000)]) if RNG.random() < 0.08 else RNG.randint(50, 2000),
                "sales_30d": RNG.randint(30, 5000),
                "rating": round(RNG.uniform(4.2, 4.9), 1),
                "return_rate_30d": round(RNG.uniform(0.02, 0.12), 3),
                "complaint_rate_30d": round(RNG.uniform(0.001, 0.03), 3),
                "regulated_category": t["regulated"],
                "sensitive_category": t["sensitive"],
                "ad_law_notes": t["note"],
                "main_image": f"images/{item_id}.jpg",
                "detail_url": f"https://mock.local/item/{item_id}",
            })
    assert len(items) == 200
    assert len({i["item_id"] for i in items}) == 200
    assert len({i["title"] for i in items}) == 200
    return items


def make_rules():
    active = [("2026-06-01", "2026-06-30")] * 22
    expired = [("2026-05-01", "2026-05-31")] * 4
    future = [("2026-07-01", "2026-07-31")] * 4
    specs = [
        # rule_id, type, title, threshold, discount_cents, discount_percent, gift, scope
        ("P001", "full_reduction", "家居日用满199减30", 19900, 3000, 0, "", {"category_l1": ["家居日用"]}),
        ("P002", "full_reduction", "美妆个护满299减50", 29900, 5000, 0, "", {"category_l1": ["美妆个护"]}),
        ("P003", "full_reduction", "食品生鲜满99减10", 9900, 1000, 0, "", {"category_l1": ["食品生鲜"]}),
        ("P004", "full_reduction", "母婴亲子满199减20", 19900, 2000, 0, "", {"category_l1": ["母婴亲子"]}),
        ("P005", "full_reduction", "3C数码满499减50", 49900, 5000, 0, "", {"category_l1": ["3C数码"]}),
        ("P006", "full_reduction", "服饰鞋包满299减30", 29900, 3000, 0, "", {"category_l1": ["服饰鞋包"]}),
        ("P007", "full_reduction", "运动户外满199减20", 19900, 2000, 0, "", {"category_l1": ["运动户外"]}),
        ("P008", "full_reduction", "保健医疗满299减50", 29900, 5000, 0, "", {"category_l1": ["保健医疗"]}),
        ("P009", "full_reduction", "全品类满499减80", 49900, 8000, 0, "", {"category_l1": ["家居日用", "美妆个护", "食品生鲜", "服饰鞋包", "3C数码", "母婴亲子", "运动户外", "保健医疗"]}),
        ("P010", "discount", "家居日用85折", 0, 0, 85, "", {"category_l1": ["家居日用"]}),
        ("P011", "discount", "美妆个护8折", 0, 0, 80, "", {"category_l1": ["美妆个护"]}),
        ("P012", "discount", "食品生鲜9折", 0, 0, 90, "", {"category_l1": ["食品生鲜"]}),
        ("P013", "discount", "3C数码95折", 0, 0, 95, "", {"category_l1": ["3C数码"]}),
        ("P014", "discount", "服饰鞋包75折", 0, 0, 75, "", {"category_l1": ["服饰鞋包"]}),
        ("P015", "coupon", "全品类满99减10券", 9900, 1000, 0, "", {"category_l1": ["家居日用", "美妆个护", "食品生鲜", "服饰鞋包", "3C数码", "母婴亲子", "运动户外", "保健医疗"]}),
        ("P016", "coupon", "母婴亲子满199减30券", 19900, 3000, 0, "", {"category_l1": ["母婴亲子"]}),
        ("P017", "gift", "美妆个护满199赠小样", 19900, 0, 0, "随机小样2件", {"category_l1": ["美妆个护"]}),
        ("P018", "gift", "食品生鲜满99赠试吃装", 9900, 0, 0, "试吃装1份", {"category_l1": ["食品生鲜"]}),
        ("P019", "full_reduction", "收纳整理满99减15", 9900, 1500, 0, "", {"category_l2": ["收纳整理"]}),
        ("P020", "discount", "面部护肤88折", 0, 0, 88, "", {"category_l2": ["面部护肤"]}),
        ("P021", "gift", "母婴亲子满299赠湿巾", 29900, 0, 0, "婴儿湿巾1包", {"category_l1": ["母婴亲子"]}),
        ("P022", "coupon", "家居日用满199减20券", 19900, 2000, 0, "", {"category_l1": ["家居日用"]}),
        ("P023", "full_reduction", "全品类满199减40（已结束）", 19900, 4000, 0, "", {"category_l1": ["家居日用", "美妆个护", "食品生鲜", "服饰鞋包", "3C数码", "母婴亲子", "运动户外", "保健医疗"]}),
        ("P024", "discount", "服饰鞋包7折（已结束）", 0, 0, 70, "", {"category_l1": ["服饰鞋包"]}),
        ("P025", "coupon", "美妆个护满299减60（已结束）", 29900, 6000, 0, "", {"category_l1": ["美妆个护"]}),
        ("P026", "gift", "食品生鲜满199赠礼盒（已结束）", 19900, 0, 0, "礼盒1份", {"category_l1": ["食品生鲜"]}),
        ("P027", "full_reduction", "全品类满299减60（未开始）", 29900, 6000, 0, "", {"category_l1": ["家居日用", "美妆个护", "食品生鲜", "服饰鞋包", "3C数码", "母婴亲子", "运动户外", "保健医疗"]}),
        ("P028", "discount", "3C数码85折（未开始）", 0, 0, 85, "", {"category_l1": ["3C数码"]}),
        ("P029", "coupon", "运动户外满199减30（未开始）", 19900, 3000, 0, "", {"category_l1": ["运动户外"]}),
        ("P030", "gift", "保健医疗满399赠礼盒（未开始）", 39900, 0, 0, "礼盒1份", {"category_l1": ["保健医疗"]}),
    ]
    assert len(specs) == 30
    periods = active + expired + future
    rules = []
    for (rid, typ, title, threshold, dc, dp, gift, scope), (start, end) in zip(specs, periods):
        rules.append({
            "rule_id": rid,
            "type": typ,
            "title": title,
            "threshold_cents": threshold,
            "discount_cents": dc,
            "discount_percent": dp,
            "gift": gift,
            "scope": scope,
            "start": start,
            "end": end,
            "stackable": False,
            "fine_print": "不与会员折扣、其他优惠叠加" if typ != "gift" else "赠品数量有限，赠完即止",
        })
    return rules


def rule_active(rule, day: date) -> bool:
    return rule["start"] <= day.isoformat() <= rule["end"]


def rule_matches(rule, item) -> bool:
    scope = rule["scope"]
    if "category_l1" in scope:
        return item["category_l1"] in scope["category_l1"]
    if "category_l2" in scope:
        return item["category_l2"] in scope["category_l2"]
    if "item_ids" in scope:
        return item["item_id"] in scope["item_ids"]
    return False


def attach_promos(items, rules):
    active_rules = [r for r in rules if rule_active(r, SCENARIO_DATE)]
    for item in items:
        matches = [r for r in active_rules if rule_matches(r, item)]
        if matches and RNG.random() < 0.68:
            chosen = RNG.choice(matches)
            item["promo_rule_ids"] = [chosen["rule_id"]]
            item["promo_tags"] = [chosen["title"]]


CITY_INFO = {
    "杭州": ("新一线", "江南", 30),
    "上海": ("一线", "江南", 25),
    "北京": ("一线", "华北", 22),
    "广州": ("一线", "华南", 18),
    "深圳": ("一线", "华南", 18),
    "成都": ("新一线", "西南", 15),
    "武汉": ("新一线", "华中", 12),
    "西安": ("新一线", "西北", 10),
    "南京": ("新一线", "江南", 12),
    "重庆": ("新一线", "西南", 10),
    "苏州": ("新一线", "江南", 10),
    "长沙": ("新一线", "华中", 8),
}

STAGE_POOL = {
    "学生": ["服饰鞋包", "3C数码", "食品生鲜", "美妆个护"],
    "新手妈妈": ["母婴亲子", "家居日用", "食品生鲜", "美妆个护"],
    "新手爸爸": ["母婴亲子", "家居日用", "食品生鲜", "3C数码"],
    "学龄家长": ["母婴亲子", "家居日用", "食品生鲜", "3C数码"],
    "单身职场": ["美妆个护", "服饰鞋包", "3C数码", "食品生鲜", "运动户外"],
    "新婚": ["家居日用", "食品生鲜", "服饰鞋包", "3C数码"],
    "空巢": ["保健医疗", "家居日用", "食品生鲜", "运动户外"],
}

STAGE_TAGS = {
    "学生": ["学生党", "预算敏感", "熬夜"],
    "新手妈妈": ["有娃", "宝妈", "爱囤货"],
    "新手爸爸": ["有娃", "奶爸", "家庭采购"],
    "学龄家长": ["有娃", "家庭采购", "品质党"],
    "单身职场": ["通勤", "租房", "熬夜"],
    "新婚": ["租房", "下厨", "品质党"],
    "空巢": ["养生", "品质党", "家庭采购"],
}

EXTRA_TAGS = ["养猫", "养狗", "健身", "露营", "护肤控", "数码控", "送礼", "减脂", "爱囤货", "预算敏感"]


def gen_users(items):
    by_l1 = {}
    for item in items:
        by_l1.setdefault(item["category_l1"], []).append(item)

    cities = list(CITY_INFO)
    weights = [CITY_INFO[c][2] for c in cities]
    age_bands = [(18, 24, 25), (25, 30, 30), (31, 38, 25), (39, 48, 15), (49, 55, 5)]

    users = []
    for n in range(1, 201):
        city = RNG.choices(cities, weights=weights, k=1)[0]
        tier, zone, _ = CITY_INFO[city]
        lo, hi, _ = RNG.choices(age_bands, weights=[b[2] for b in age_bands], k=1)[0]
        age = RNG.randint(lo, hi)
        gender = "女" if RNG.random() < 0.55 else "男"

        if age <= 22:
            stage = "学生"
        elif age <= 27:
            stage = RNG.choices(["单身职场", "新婚"], [0.75, 0.25])[0]
        elif age <= 33:
            stage = RNG.choices(["新手妈妈", "新手爸爸", "单身职场", "新婚"], [0.35, 0.15, 0.30, 0.20])[0]
        elif age <= 42:
            stage = RNG.choices(["学龄家长", "单身职场", "新婚"], [0.60, 0.20, 0.20])[0]
        else:
            stage = RNG.choices(["空巢", "学龄家长"], [0.50, 0.50])[0]

        if stage == "新手妈妈":
            gender = "女"
        elif stage == "新手爸爸":
            gender = "男"
        elif stage == "学生":
            age = min(age, 24)

        is_new = RNG.random() < 0.10
        account_age = RNG.randint(1, 30) if is_new else RNG.randint(60, 1800)

        level = RNG.choices(["L1", "L2", "L3", "L4", "L5"], [15, 30, 30, 18, 7])[0]
        aov_range = {"L1": (30, 80), "L2": (80, 160), "L3": (160, 320), "L4": (320, 700), "L5": (700, 1600)}[level]
        aov = round(RNG.uniform(*aov_range), 2)
        orders = {
            "L1": RNG.randint(1, 8), "L2": RNG.randint(3, 15), "L3": RNG.randint(6, 25),
            "L4": RNG.randint(10, 35), "L5": RNG.randint(15, 50),
        }[level]
        if is_new:
            orders = min(orders, RNG.randint(0, 3))

        sens_weights = {
            "L1": [70, 25, 5], "L2": [65, 28, 7], "L3": [30, 50, 20],
            "L4": [10, 40, 50], "L5": [5, 25, 70],
        }[level]
        sensitivity = RNG.choices(["high", "mid", "low"], sens_weights)[0]

        tags = list(STAGE_TAGS[stage])
        for tag in RNG.sample(EXTRA_TAGS, k=RNG.randint(0, 2)):
            if tag not in tags:
                tags.append(tag)
        tags = tags[:4]

        preferred = RNG.sample(STAGE_POOL[stage], k=3)
        if RNG.random() < 0.25:
            preferred = preferred[:2]

        female_l3 = {"口红", "身体乳", "内衣"}
        kids_l3 = {"纸尿裤", "婴儿湿巾", "积木", "童装T恤", "奶瓶"}
        female_spec_tokens = ("女款", "粉白", "浅粉", "粉色", "玫瑰", "豆沙", "正红", "枫叶", "奶茶", "莓果", "肤色")
        gift_intent = "送礼" in tags

        def eligible(item):
            if gender == "男" and not gift_intent:
                if item["category_l3"] in female_l3:
                    return False
                if any(tok in item["spec"] for tok in female_spec_tokens):
                    return False
            if stage not in {"新手妈妈", "新手爸爸", "学龄家长"} and item["category_l3"] in kids_l3:
                return False
            return True

        pool = [i for cat in preferred for i in by_l1[cat] if eligible(i)]
        if not pool:
            pool = [i for cat in preferred for i in by_l1[cat]]
        cart_k = min(len(pool), RNG.randint(0, 4))
        if is_new:
            order_k = min(len(pool), RNG.randint(0, min(2, max(orders, 0))))
        elif orders > 0:
            order_k = min(len(pool), RNG.randint(1, min(5, orders)))
        else:
            order_k = 0
        cart = RNG.sample(pool, k=cart_k) if pool else []
        recent_orders = RNG.sample(pool, k=order_k) if pool else []
        if RNG.random() < 0.2:
            other = [i for i in items if i["category_l1"] not in preferred and eligible(i)]
            if other:
                extra = RNG.choice(other)
                if extra not in cart:
                    cart.append(extra)

        l3_pool = sorted({i["category_l3"] for i in pool})
        intents = ["平价", "推荐", "测评", "家用", "送礼"]
        search_count = RNG.randint(2, 3)
        searches = RNG.sample(l3_pool, k=min(len(l3_pool), search_count - 1))
        searches.append(RNG.choice(intents))
        searches = list(dict.fromkeys(searches))[:3]

        night_owl = RNG.random() < 0.22
        active_hours = "22:00-02:00" if night_owl else RNG.choice(["07:00-23:00", "08:00-22:00", "09:00-23:00"])

        member = "88VIP" if (not is_new and account_age >= 180 and RNG.random() < 0.22) else "normal"
        status = "normal"
        if not is_new:
            status = RNG.choices(["normal", "risk_control", "limited"], [0.93, 0.04, 0.03])[0]

        users.append({
            "user_id": f"u_{n:04d}",
            "city": city,
            "city_tier": tier,
            "climate_zone": zone,
            "age": age,
            "gender": gender,
            "life_stage": stage,
            "member_level": member,
            "account_age_days": account_age,
            "account_status": status,
            "consumption_level": level,
            "aov_90d": aov,
            "orders_90d": orders,
            "price_sensitivity": sensitivity,
            "preferred_categories": preferred,
            "night_owl": night_owl,
            "active_hours": active_hours,
            "recent_cart_item_ids": [i["item_id"] for i in cart],
            "recent_order_item_ids": [i["item_id"] for i in recent_orders],
            "last_search_terms": searches,
            "tags": tags,
        })
    assert len(users) == 200
    assert len({u["user_id"] for u in users}) == 200
    return users


def gen_history():
    l2s = sorted({t["l2"] for t in TYPES})
    hooks = ["季节", "地域", "人群", "价格", "场景", "功效", "情绪"]
    rows = []
    for n in range(1, 31):
        l2 = l2s[(n - 1) % len(l2s)]
        hook = hooks[(n - 1) % len(hooks)]
        ctr = round(RNG.uniform(0.025, 0.075), 3)
        refund = round(RNG.uniform(0.03, 0.10), 3)
        complaint = round(RNG.uniform(0.002, 0.015), 3)
        block = round(RNG.uniform(0.005, 0.04), 3)
        if hook == "功效":
            refund = round(refund + 0.03, 3)
            complaint = round(complaint + 0.008, 3)
            block = round(block + 0.02, 3)
        if hook == "价格":
            refund = round(refund + 0.015, 3)
        rows.append({
            "pattern_id": f"HS{n:02d}",
            "category_l2": l2,
            "hook_type": hook,
            "ctr": ctr,
            "refund_rate": refund,
            "complaint_rate": complaint,
            "block_rate": block,
            "n": RNG.randint(100, 2000),
        })
    return rows


LEXICON = [
    ("最", "absolute_claim", "high", "广告法第9条", "最高级表述"),
    ("最佳", "absolute_claim", "high", "广告法第9条", "最高级表述"),
    ("最好", "absolute_claim", "high", "广告法第9条", "最高级表述"),
    ("最低价", "absolute_claim", "high", "广告法第9条", "价格绝对化"),
    ("全网最低", "absolute_claim", "high", "广告法第9条", "价格绝对化"),
    ("第一", "absolute_claim", "high", "广告法第9条", "排名绝对化"),
    ("顶级", "absolute_claim", "high", "广告法第9条", "等级绝对化"),
    ("国家级", "absolute_claim", "high", "广告法第9条", "资质绝对化"),
    ("领先", "absolute_claim", "high", "广告法第9条", "地位绝对化"),
    ("独家", "absolute_claim", "high", "广告法第9条", "排他性表述"),
    ("首创", "absolute_claim", "high", "广告法第9条", "首创性表述"),
    ("唯一", "absolute_claim", "high", "广告法第9条", "排他性表述"),
    ("100%", "absolute_claim", "high", "广告法第9条", "效果绝对化"),
    ("绝对", "absolute_claim", "high", "广告法第9条", "绝对化表述"),
    ("天花板", "absolute_claim", "high", "广告法第9条", "网络绝对化表述"),
    ("防潮", "efficacy_or_medical_claim", "high", "广告法第28条", "功能宣称需属性支撑"),
    ("除湿", "efficacy_or_medical_claim", "high", "广告法第28条", "功能宣称需属性支撑"),
    ("杀菌", "efficacy_or_medical_claim", "high", "广告法第28条", "消毒功效需资质"),
    ("消炎", "efficacy_or_medical_claim", "critical", "广告法第17条", "医疗用语"),
    ("治疗", "efficacy_or_medical_claim", "critical", "广告法第17条", "医疗用语"),
    ("根治", "efficacy_or_medical_claim", "critical", "广告法第17条", "医疗用语"),
    ("美白", "efficacy_or_medical_claim", "high", "广告法第28条", "特殊化妆品功效"),
    ("祛斑", "efficacy_or_medical_claim", "high", "广告法第28条", "特殊化妆品功效"),
    ("减肥", "efficacy_or_medical_claim", "high", "广告法第28条", "身体功效宣称"),
    ("瘦身", "efficacy_or_medical_claim", "high", "广告法第28条", "身体功效宣称"),
    ("生发", "efficacy_or_medical_claim", "high", "广告法第28条", "特殊化妆品功效"),
    ("防脱", "efficacy_or_medical_claim", "high", "广告法第28条", "特殊化妆品功效"),
    ("抗衰", "efficacy_or_medical_claim", "high", "广告法第28条", "抗衰功效需依据"),
    ("祛痘", "efficacy_or_medical_claim", "high", "广告法第28条", "功效宣称需依据"),
    ("除螨", "efficacy_or_medical_claim", "high", "广告法第28条", "功效宣称需依据"),
    ("驱蚊", "efficacy_or_medical_claim", "high", "广告法第28条", "农药登记要求"),
    ("助眠", "efficacy_or_medical_claim", "high", "广告法第28条", "保健功效宣称"),
    ("增强免疫力", "efficacy_or_medical_claim", "high", "广告法第28条", "保健功能宣称"),
    ("医用", "efficacy_or_medical_claim", "critical", "广告法第17条", "医疗用语"),
    ("处方", "efficacy_or_medical_claim", "critical", "广告法第17条", "医疗用语"),
    ("疗程", "efficacy_or_medical_claim", "critical", "广告法第17条", "医疗用语"),
    ("治愈", "efficacy_or_medical_claim", "critical", "广告法第17条", "医疗用语"),
    ("无副作用", "efficacy_or_medical_claim", "critical", "广告法第17条", "医疗安全性表述"),
    ("原价", "price_misleading", "medium", "广告法第28条", "价格比较需真实"),
    ("到手价", "price_misleading", "medium", "广告法第28条", "价格表述需可核验"),
    ("仅需", "price_misleading", "medium", "广告法第28条", "价格诱导表述"),
    ("低至", "price_misleading", "medium", "广告法第28条", "价格区间需真实"),
    ("秒杀", "price_misleading", "medium", "广告法第28条", "限时价格需真实"),
    ("清仓", "price_misleading", "medium", "广告法第28条", "清仓表述需真实"),
    ("亏本", "price_misleading", "medium", "广告法第28条", "价格比较需真实"),
]

VARIANTS = [
    ("蕞", "最", "谐音"),
    ("最①", "最", "符号"),
    ("zui", "最", "拼音"),
    ("NO.1", "第一", "英文"),
    ("TOP1", "第一", "英文"),
    ("頂級", "顶级", "繁体"),
    ("天花板级别", "天花板", "隐喻"),
    ("封神", "顶级", "网络语"),
    ("王炸", "顶级", "网络语"),
    ("絶对", "绝对", "繁体"),
    ("100％", "100%", "全角"),
    ("全网zui低", "全网最低", "混写"),
    ("除濕", "除湿", "繁体"),
    ("防潮神器", "防潮", "组合词"),
    ("美白淡斑", "美白", "组合词"),
    ("祛斑美白", "祛斑", "组合词"),
    ("药到病除", "治愈", "成语"),
    ("无副作用", "无副作用", "短语"),
    ("僅需", "仅需", "繁体"),
    ("低至", "低至", "短语"),
]


def write_csv(path: Path, rows, fields, list_fields):
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            out = {}
            for key in fields:
                value = row[key]
                if key in list_fields:
                    out[key] = "|".join(str(v) for v in value)
                elif isinstance(value, bool):
                    out[key] = "true" if value else "false"
                else:
                    out[key] = value
            writer.writerow(out)


def build_db(users, items, rules, history):
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE users (
          user_id TEXT PRIMARY KEY, city TEXT, city_tier TEXT, climate_zone TEXT,
          age INTEGER, gender TEXT, life_stage TEXT, member_level TEXT,
          account_age_days INTEGER, account_status TEXT, consumption_level TEXT,
          aov_90d REAL, orders_90d INTEGER, price_sensitivity TEXT,
          preferred_categories TEXT, night_owl INTEGER, active_hours TEXT,
          recent_cart_item_ids TEXT, recent_order_item_ids TEXT,
          last_search_terms TEXT, tags TEXT
        );
        CREATE TABLE items (
          item_id TEXT PRIMARY KEY, title TEXT, brand TEXT,
          category_l1 TEXT, category_l2 TEXT, category_l3 TEXT,
          functions TEXT, material TEXT, spec TEXT,
          suit_audience TEXT, suit_season TEXT,
          efficacy_claims_allowed TEXT, qualifications TEXT,
          price_cents INTEGER, original_price_cents INTEGER,
          promo_tags TEXT, promo_rule_ids TEXT,
          stock INTEGER, sales_30d INTEGER, rating REAL,
          return_rate_30d REAL, complaint_rate_30d REAL,
          regulated_category TEXT, sensitive_category INTEGER,
          ad_law_notes TEXT, main_image TEXT, detail_url TEXT
        );
        CREATE TABLE promo_rules (
          rule_id TEXT PRIMARY KEY, type TEXT, title TEXT,
          rule_json TEXT, start TEXT, end TEXT
        );
        CREATE TABLE lexicon (
          term TEXT, canonical TEXT, risk_type TEXT,
          severity TEXT, law_ref TEXT, note TEXT
        );
        CREATE TABLE lexicon_variants (
          variant TEXT, canonical TEXT, type TEXT
        );
        CREATE TABLE history_stats (
          pattern_id TEXT PRIMARY KEY, category_l2 TEXT, hook_type TEXT,
          ctr REAL, refund_rate REAL, complaint_rate REAL,
          block_rate REAL, n INTEGER
        );
        CREATE INDEX idx_items_l1 ON items(category_l1);
        CREATE INDEX idx_items_l2 ON items(category_l2);
        CREATE INDEX idx_items_sensitive ON items(sensitive_category);
        CREATE INDEX idx_lexicon_term ON lexicon(term);
        """
    )

    def j(v):
        return json.dumps(v, ensure_ascii=False)

    cur.executemany(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                u["user_id"], u["city"], u["city_tier"], u["climate_zone"], u["age"],
                u["gender"], u["life_stage"], u["member_level"], u["account_age_days"],
                u["account_status"], u["consumption_level"], u["aov_90d"], u["orders_90d"],
                u["price_sensitivity"], j(u["preferred_categories"]), int(u["night_owl"]),
                u["active_hours"], j(u["recent_cart_item_ids"]), j(u["recent_order_item_ids"]),
                j(u["last_search_terms"]), j(u["tags"]),
            )
            for u in users
        ],
    )
    cur.executemany(
        "INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                i["item_id"], i["title"], i["brand"], i["category_l1"], i["category_l2"],
                i["category_l3"], j(i["functions"]), i["material"], i["spec"],
                i["suit_audience"], i["suit_season"], j(i["efficacy_claims_allowed"]),
                j(i["qualifications"]), i["price_cents"], i["original_price_cents"],
                j(i["promo_tags"]), j(i["promo_rule_ids"]), i["stock"], i["sales_30d"],
                i["rating"], i["return_rate_30d"], i["complaint_rate_30d"],
                i["regulated_category"], int(i["sensitive_category"]), i["ad_law_notes"],
                i["main_image"], i["detail_url"],
            )
            for i in items
        ],
    )
    cur.executemany(
        "INSERT INTO promo_rules VALUES (?,?,?,?,?,?)",
        [(r["rule_id"], r["type"], r["title"], j(r), r["start"], r["end"]) for r in rules],
    )
    cur.executemany(
        "INSERT INTO lexicon VALUES (?,?,?,?,?,?)",
        [(term, term, risk, sev, law, note) for term, risk, sev, law, note in LEXICON],
    )
    cur.executemany(
        "INSERT INTO lexicon_variants VALUES (?,?,?)",
        VARIANTS,
    )
    cur.executemany(
        "INSERT INTO history_stats VALUES (?,?,?,?,?,?,?,?)",
        [(h["pattern_id"], h["category_l2"], h["hook_type"], h["ctr"], h["refund_rate"],
          h["complaint_rate"], h["block_rate"], h["n"]) for h in history],
    )
    conn.commit()
    conn.close()


def main():
    items = gen_items()
    rules = make_rules()
    attach_promos(items, rules)
    users = gen_users(items)
    history = gen_history()

    user_fields = [
        "user_id", "city", "city_tier", "climate_zone", "age", "gender", "life_stage",
        "member_level", "account_age_days", "account_status", "consumption_level",
        "aov_90d", "orders_90d", "price_sensitivity", "preferred_categories",
        "night_owl", "active_hours", "recent_cart_item_ids", "recent_order_item_ids",
        "last_search_terms", "tags",
    ]
    item_fields = [
        "item_id", "title", "brand", "category_l1", "category_l2", "category_l3",
        "functions", "material", "spec", "suit_audience", "suit_season",
        "efficacy_claims_allowed", "qualifications", "price_cents",
        "original_price_cents", "promo_tags", "promo_rule_ids", "stock", "sales_30d",
        "rating", "return_rate_30d", "complaint_rate_30d", "regulated_category",
        "sensitive_category", "ad_law_notes", "main_image", "detail_url",
    ]
    list_user_fields = {
        "preferred_categories", "recent_cart_item_ids", "recent_order_item_ids",
        "last_search_terms", "tags",
    }
    list_item_fields = {
        "functions", "efficacy_claims_allowed", "qualifications", "promo_tags", "promo_rule_ids",
    }

    write_csv(RAW / "users.csv", users, user_fields, list_user_fields)
    write_csv(RAW / "items.csv", items, item_fields, list_item_fields)

    with (RAW / "promo_rules.json").open("w", encoding="utf-8") as fh:
        json.dump(rules, fh, ensure_ascii=False, indent=2)

    with (RAW / "compliance_lexicon.txt").open("w", encoding="utf-8") as fh:
        for term, risk, sev, law, note in LEXICON:
            fh.write(f"{term}|{term}|{risk}|{sev}|{law}|{note}\n")

    with (RAW / "lexicon_variants.tsv").open("w", encoding="utf-8") as fh:
        fh.write("variant\tcanonical\ttype\n")
        for variant, canonical, typ in VARIANTS:
            fh.write(f"{variant}\t{canonical}\t{typ}\n")

    history_fields = ["pattern_id", "category_l2", "hook_type", "ctr", "refund_rate",
                      "complaint_rate", "block_rate", "n"]
    write_csv(RAW / "history_reason_stats.csv", history, history_fields, set())

    climate = {
        city: {
            "city_tier": tier,
            "climate_zone": zone,
            "monsoon_months": [6, 7] if zone == "江南" else ([5, 6, 7, 8] if zone == "华南" else []),
            "notes": "6 月为梅雨季" if city in {"杭州", "上海", "南京", "苏州"} else "按季节规则生成",
        }
        for city, (tier, zone, _) in CITY_INFO.items()
    }
    with (RAW / "city_climate.json").open("w", encoding="utf-8") as fh:
        json.dump(climate, fh, ensure_ascii=False, indent=2)

    build_db(users, items, rules, history)

    print(f"users={len(users)} items={len(items)} rules={len(rules)} "
          f"lexicon={len(LEXICON)} variants={len(VARIANTS)} history={len(history)}")
    print(f"db={DB_PATH.relative_to(ROOT)}")
    print(f"promo coverage={sum(1 for i in items if i['promo_rule_ids'])}/{len(items)}")


if __name__ == "__main__":
    main()

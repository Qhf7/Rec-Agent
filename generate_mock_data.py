import csv
import random
from pathlib import Path

SEED = 20261116
N = 200
rng = random.Random(SEED)

ROOT = Path(__file__).resolve().parent

# -----------------------------
# Users
# -----------------------------
provinces = [
    ("浙江", ["杭州", "宁波", "温州", "嘉兴"]),
    ("江苏", ["南京", "苏州", "无锡", "常州"]),
    ("广东", ["广州", "深圳", "佛山", "东莞"]),
    ("四川", ["成都", "绵阳", "德阳"]),
    ("湖北", ["武汉", "宜昌", "襄阳"]),
    ("山东", ["济南", "青岛", "烟台"]),
    ("福建", ["福州", "厦门", "泉州"]),
    ("北京", ["北京"]),
    ("上海", ["上海"]),
    ("湖南", ["长沙", "株洲"]),
]
age_bands = ["18-24", "25-29", "30-34", "35-39", "40-49", "50+"]
genders = ["女", "男", "其他/未填写"]
occupations = ["学生", "互联网从业者", "教师", "医护人员", "行政/运营", "个体经营", "工程师", "自由职业"]
income_bands = ["低", "中低", "中", "中高", "高"]
interest_pool = [
    "数码", "家居收纳", "户外运动", "美妆护肤", "母婴", "零食饮料", "服饰穿搭", "宠物用品",
    "旅行", "健身", "咖啡茶饮", "厨房烹饪", "阅读", "摄影", "汽车用品", "家电", "园艺", "潮玩",
]
category_pool = [
    "手机数码", "家居日用", "家用电器", "服饰鞋包", "美妆个护", "食品饮料", "运动户外",
    "母婴用品", "宠物用品", "汽车用品", "家具家装", "玩具潮玩", "图书文娱", "鲜花园艺",
]
time_slots = ["清晨", "上午", "午间", "下午", "晚间", "深夜"]
price_ranges = ["0-50", "50-100", "100-300", "300-800", "800-2000", "2000+"]
discount_types = ["满减", "直降", "折扣", "优惠券", "会员价", "无偏好"]
account_statuses = ["正常", "新注册", "高活跃", "沉默召回", "风险观察"]
activity_levels = ["低", "中", "高", "极高"]
weather_sensitivities = ["低", "中", "高"]

user_rows = []
for i in range(1, N + 1):
    province, cities = rng.choice(provinces)
    city = rng.choice(cities)
    interests = rng.sample(interest_pool, k=rng.randint(3, 5))
    recent_categories = rng.sample(category_pool, k=rng.randint(2, 4))
    history_ids = rng.sample(range(1, 201), k=rng.randint(2, 6))
    cart_ids = rng.sample(range(1, 201), k=rng.randint(0, 3))
    active_slots = rng.sample(time_slots, k=rng.randint(1, 3))
    row = {
        "user_id": f"u_{i:04d}",
        "province": province,
        "city": city,
        "age_band": rng.choice(age_bands),
        "gender": rng.choice(genders),
        "occupation": rng.choice(occupations),
        "income_band": rng.choice(income_bands),
        "interests": "|".join(interests),
        "recent_categories": "|".join(recent_categories),
        "purchase_history_item_ids": ";".join(f"item_{x:04d}" for x in history_ids),
        "cart_item_ids": ";".join(f"item_{x:04d}" for x in cart_ids),
        "browse_time_slots": "|".join(active_slots),
        "preferred_price_range": rng.choice(price_ranges),
        "preferred_discount_type": rng.choice(discount_types),
        "weather_sensitivity": rng.choice(weather_sensitivities),
        "account_status": rng.choice(account_statuses),
        "activity_level": rng.choice(activity_levels),
        "ai_disclosure_preference": rng.choice(["接受", "无偏好", "希望明确标识"]),
        "profile_version": f"profile-v{rng.randint(1, 4)}",
    }
    user_rows.append(row)

user_fields = list(user_rows[0].keys())
with (ROOT / "users.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=user_fields)
    writer.writeheader()
    writer.writerows(user_rows)

# -----------------------------
# Items
# -----------------------------
product_families = [
    {
        "category": "家居日用", "subcategory": "收纳整理", "brand_prefix": ["简居", "好收纳", "木棉家"],
        "titles": ["折叠收纳盒", "衣物防尘袋", "抽屉分隔盒", "桌面理线器", "旅行收纳包"],
        "descriptions": ["适合衣物、玩具与小件物品分类整理", "轻便可折叠，适合换季收纳", "小户型桌面与抽屉整理工具"],
        "functions": ["折叠", "防尘", "分区收纳", "便携", "理线"],
        "materials": ["PP塑料", "牛津布", "竹纤维", "涤纶", "ABS"],
        "scenes": ["卧室整理", "租房收纳", "旅行整理", "办公桌整理"],
        "tags": ["收纳", "小户型", "租房党", "搬家"],
        "price": (19, 129), "risk_tags": ["none", "off_topic_sensitive"],
    },
    {
        "category": "家用电器", "subcategory": "环境电器", "brand_prefix": ["清风", "云朵", "森呼吸"],
        "titles": ["迷你除湿机", "静音循环扇", "桌面加湿器", "空气循环扇", "衣柜除湿盒"],
        "descriptions": ["适合卧室、书房等小空间使用", "低噪运行，帮助改善局部空气体感", "便于桌面或衣柜摆放"],
        "functions": ["除湿", "循环送风", "加湿", "定时", "低噪", "水满提醒"],
        "materials": ["ABS", "铝合金", "PP塑料", "电子元件"],
        "scenes": ["梅雨季", "卧室", "书房", "衣柜", "办公桌"],
        "tags": ["防潮", "降噪", "梅雨季", "小空间"],
        "price": (49, 699), "risk_tags": ["efficacy_sensitive", "none"],
    },
    {
        "category": "美妆个护", "subcategory": "护肤", "brand_prefix": ["澄肌", "花间序", "润研"],
        "titles": ["舒缓保湿面霜", "清爽防晒乳", "氨基酸洁面", "护手霜", "头皮按摩梳"],
        "descriptions": ["日常清洁与保湿护理产品", "配方信息与使用说明以商品详情页为准", "适合日常通勤与居家护理"],
        "functions": ["保湿", "清洁", "防晒", "舒缓", "按摩"],
        "materials": ["乳霜配方", "氨基酸表活", "植物油脂", "硅胶", "塑料"],
        "scenes": ["日常护肤", "通勤", "旅行", "换季护理"],
        "tags": ["护肤", "通勤", "换季", "轻护理"],
        "price": (29, 399), "risk_tags": ["medical_claim_sensitive", "none"],
    },
    {
        "category": "食品饮料", "subcategory": "休闲零食", "brand_prefix": ["谷小满", "原野食集", "果然多"],
        "titles": ["低糖坚果礼盒", "冻干水果脆", "燕麦能量棒", "乌龙茶饮料", "手工曲奇"],
        "descriptions": ["日常分享与办公室零食选择", "配料和营养信息以包装标识为准", "适合下午茶与出行携带"],
        "functions": ["独立包装", "便携", "低糖配方", "即饮", "分享装"],
        "materials": ["食品原料", "铝塑复合膜", "纸盒", "PET瓶"],
        "scenes": ["办公室", "下午茶", "旅行出行", "节日送礼"],
        "tags": ["零食", "下午茶", "送礼", "便携"],
        "price": (12, 189), "risk_tags": ["absolute_claim_sensitive", "none"],
    },
    {
        "category": "运动户外", "subcategory": "运动装备", "brand_prefix": ["野行", "轻跃", "动感线"],
        "titles": ["轻量跑鞋", "速干运动T恤", "折叠瑜伽垫", "露营折叠椅", "防晒冰袖"],
        "descriptions": ["适合日常运动与短途户外活动", "尺码和承重信息以详情页参数为准", "轻量设计方便携带"],
        "functions": ["轻量", "速干", "防滑", "折叠", "透气", "便携"],
        "materials": ["网布", "EVA", "聚酯纤维", "铝合金", "尼龙"],
        "scenes": ["跑步", "健身房", "露营", "通勤", "短途旅行"],
        "tags": ["运动", "户外", "露营", "旅行"],
        "price": (39, 899), "risk_tags": ["absolute_claim_sensitive", "none"],
    },
    {
        "category": "母婴用品", "subcategory": "婴童用品", "brand_prefix": ["小树苗", "暖芽", "萌护"],
        "titles": ["婴儿连体衣", "可拆洗围兜", "儿童餐具套装", "婴儿湿巾", "学步防撞条"],
        "descriptions": ["面向家庭日常照护与出行场景", "适用年龄和使用注意事项以详情页为准", "方便清洁和收纳"],
        "functions": ["可拆洗", "防水", "柔软", "分格", "防撞", "便携"],
        "materials": ["纯棉", "食品级硅胶", "无纺布", "EVA", "PP"],
        "scenes": ["婴儿护理", "家庭用餐", "外出携带", "儿童房"],
        "tags": ["母婴", "新手爸妈", "儿童", "家庭"],
        "price": (16, 299), "risk_tags": ["medical_claim_sensitive", "none"],
    },
    {
        "category": "宠物用品", "subcategory": "宠物日用", "brand_prefix": ["毛球星球", "喵趣", "尾巴管家"],
        "titles": ["猫咪饮水机", "宠物除味豆腐砂", "可折叠宠物窝", "互动漏食球", "宠物梳毛器"],
        "descriptions": ["适合猫犬家庭的日常用品", "根据宠物体型和习惯选择规格", "易清洁、便于收纳"],
        "functions": ["循环饮水", "除味", "折叠", "互动", "梳毛", "易清洁"],
        "materials": ["PP", "硅胶", "植物纤维", "涤纶", "不锈钢"],
        "scenes": ["居家养宠", "宠物出行", "换毛季", "租房"],
        "tags": ["宠物", "猫咪", "狗狗", "除味"],
        "price": (25, 499), "risk_tags": ["efficacy_sensitive", "none"],
    },
    {
        "category": "手机数码", "subcategory": "数码配件", "brand_prefix": ["极简数码", "闪联", "微光科技"],
        "titles": ["65W氮化镓充电器", "磁吸手机支架", "无线键盘", "降噪蓝牙耳机", "桌面充电底座"],
        "descriptions": ["适合办公、出行和桌面使用", "接口、兼容性和续航以规格页为准", "轻量设计便于携带"],
        "functions": ["快充", "磁吸", "无线连接", "降噪", "多设备兼容", "折叠"],
        "materials": ["PC", "铝合金", "ABS", "锂电池", "硅胶"],
        "scenes": ["办公桌", "差旅", "通勤", "居家娱乐"],
        "tags": ["数码", "办公", "通勤", "快充"],
        "price": (39, 1299), "risk_tags": ["absolute_claim_sensitive", "none"],
    },
    {
        "category": "汽车用品", "subcategory": "车载用品", "brand_prefix": ["行迹", "车友汇", "途安"],
        "titles": ["车载手机支架", "汽车座椅收纳袋", "便携洗车水枪", "车内香氛", "应急启动电源"],
        "descriptions": ["用于车内整理、清洁与出行辅助", "安装方式和适配车型以详情页为准", "便于放在后备箱备用"],
        "functions": ["固定", "收纳", "便携", "清洁", "香氛", "应急启动"],
        "materials": ["ABS", "PU皮", "尼龙", "铝合金", "锂电池"],
        "scenes": ["日常通勤", "自驾旅行", "车内整理", "应急备用"],
        "tags": ["汽车", "通勤", "自驾", "应急"],
        "price": (29, 799), "risk_tags": ["efficacy_sensitive", "none"],
    },
    {
        "category": "家具家装", "subcategory": "家装小件", "brand_prefix": ["木作日常", "住好家", "原木工坊"],
        "titles": ["可调节书桌", "床边小推车", "壁挂置物架", "人体工学坐垫", "折叠换鞋凳"],
        "descriptions": ["适合小户型与居家办公的实用家具", "尺寸、承重和安装方式以参数页为准", "简洁设计方便搭配"],
        "functions": ["可调节", "带轮移动", "壁挂", "减压支撑", "折叠", "易安装"],
        "materials": ["板材", "钢架", "竹木", "海绵", "织物"],
        "scenes": ["居家办公", "卧室", "玄关", "租房"],
        "tags": ["家装", "小户型", "办公", "收纳"],
        "price": (59, 1599), "risk_tags": ["efficacy_sensitive", "none"],
    },
    {
        "category": "服饰鞋包", "subcategory": "女装", "brand_prefix": ["日常衣橱", "漫步衣舍", "轻氧穿搭"],
        "titles": ["防晒衬衫", "通勤针织开衫", "宽松直筒裤", "轻便帆布鞋", "旅行双肩包"],
        "descriptions": ["适合通勤、旅行和日常穿搭", "版型和面料信息以尺码表为准", "基础款便于搭配"],
        "functions": ["防晒", "透气", "宽松版型", "轻便", "多口袋", "可机洗"],
        "materials": ["棉", "涤纶", "帆布", "PU", "粘纤"],
        "scenes": ["通勤", "旅行", "周末出行", "日常穿搭"],
        "tags": ["服饰", "通勤", "旅行", "轻便"],
        "price": (49, 599), "risk_tags": ["absolute_claim_sensitive", "none"],
    },
    {
        "category": "鲜花园艺", "subcategory": "家庭园艺", "brand_prefix": ["绿意生活", "小院子", "植趣"],
        "titles": ["阳台香草种植套装", "自动浇水花盆", "室内绿植组合", "园艺修枝剪", "多肉植物土"],
        "descriptions": ["适合阳台、窗台和室内绿植养护", "植物状态受光照、温度和养护方式影响", "新手也能按说明操作"],
        "functions": ["自动浇水", "透气", "保水", "修枝", "便携", "易种植"],
        "materials": ["陶土", "PP", "不锈钢", "椰糠", "泥炭"],
        "scenes": ["阳台", "窗台", "室内绿植", "周末园艺"],
        "tags": ["园艺", "绿植", "阳台", "新手"],
        "price": (15, 299), "risk_tags": ["efficacy_sensitive", "none"],
    },
    {
        "category": "图书文娱", "subcategory": "图书", "brand_prefix": ["知行书房", "纸上时光", "阅读派"],
        "titles": ["时间管理手册", "儿童科普绘本", "旅行摄影指南", "家庭烘焙入门", "推理小说精选"],
        "descriptions": ["适合阅读、学习和兴趣培养", "内容简介和目录以商品详情页为准", "纸张与装帧适合日常阅读"],
        "functions": ["图文讲解", "案例练习", "便携阅读", "亲子共读", "章节导读"],
        "materials": ["胶版纸", "铜版纸", "精装封面", "平装封面"],
        "scenes": ["通勤阅读", "亲子阅读", "周末学习", "旅行准备"],
        "tags": ["阅读", "学习", "亲子", "兴趣"],
        "price": (19, 199), "risk_tags": ["off_topic_sensitive", "none"],
    },
    {
        "category": "玩具潮玩", "subcategory": "潮玩模型", "brand_prefix": ["潮玩社", "小宇宙工坊", "乐模"],
        "titles": ["盲盒潮玩", "拼装积木套装", "桌面解压摆件", "可动模型", "儿童磁力片"],
        "descriptions": ["适合收藏、拼装和亲子互动", "具体款式随机或以选择页为准", "请按照年龄建议使用"],
        "functions": ["随机款式", "可拼装", "可动关节", "桌面摆放", "亲子互动"],
        "materials": ["ABS", "PVC", "纸质包装", "磁性材料"],
        "scenes": ["收藏展示", "亲子互动", "桌面娱乐", "节日礼物"],
        "tags": ["潮玩", "礼物", "亲子", "收藏"],
        "price": (29, 499), "risk_tags": ["absolute_claim_sensitive", "none"],
    },
]

item_rows = []
item_no = 1
for family_idx, family in enumerate(product_families):
    for variant in range(1, 16):
        if item_no > N:
            break
        brand = rng.choice(family["brand_prefix"])
        base_title = rng.choice(family["titles"])
        title = f"{brand}{base_title}{['标准款', '升级款', '轻享款', '便携款', '家用款'][variant % 5]}"
        low, high = family["price"]
        original_price = rng.randint(low + 5, high + 80)
        price = round(rng.uniform(low, min(high, original_price)), 2)
        if price >= original_price:
            price = round(original_price * rng.uniform(0.55, 0.9), 2)
        functions = rng.sample(family["functions"], k=min(3, len(family["functions"])))
        scenes = rng.sample(family["scenes"], k=min(2, len(family["scenes"])))
        tags = rng.sample(family["tags"], k=min(3, len(family["tags"])))
        risk_tag = rng.choice(family["risk_tags"])
        promo_ids = []
        activity_flag = "无活动"
        if item_no % 4 == 0:
            promo_ids = [f"promo_{(item_no % 12) + 1:03d}"]
            activity_flag = rng.choice(["满减", "直降", "优惠券", "会员价"])
        elif item_no % 7 == 0:
            promo_ids = [f"promo_{(item_no % 12) + 1:03d}"]
            activity_flag = "限时折扣"
        row = {
            "item_id": f"item_{item_no:04d}",
            "title": title,
            "category": family["category"],
            "subcategory": family["subcategory"],
            "brand": brand,
            "description": rng.choice(family["descriptions"]),
            "functions": "|".join(functions),
            "materials": "|".join(rng.sample(family["materials"], k=min(2, len(family["materials"])))),
            "suitable_scenes": "|".join(scenes),
            "target_tags": "|".join(tags),
            "price": f"{price:.2f}",
            "original_price": f"{original_price:.2f}",
            "stock": rng.randint(20, 5000),
            "promo_ids": "|".join(promo_ids),
            "activity_flag": activity_flag,
            "main_image_path": f"/mock_assets/items/item_{item_no:04d}.jpg",
            "risk_tags": risk_tag,
        }
        item_rows.append(row)
        item_no += 1
    if item_no > N:
        break

item_fields = list(item_rows[0].keys())
with (ROOT / "items.csv").open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=item_fields)
    writer.writeheader()
    writer.writerows(item_rows)

print(f"generated users.csv: {len(user_rows)} rows")
print(f"generated items.csv: {len(item_rows)} rows")

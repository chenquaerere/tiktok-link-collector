"""测试 fixture：模拟真实 TikTok item_list 响应结构（探针验证过）。

字段与真实 /api/post/item_list/ 一致：
- itemList[].id = video_id（19位）
- itemList[].createTime = Unix 秒级时间戳（绝对发布时间）
- itemList[].author.uniqueId = 用户名
- itemList[].desc = 文案
"""
import json

# 真实 createTime（探针 @demo_alpha 验证）→ 北京时间
TODAY_09_24 = {
    "7689051423832575252": 1790246798,  # 18:46:38
    "7689037154575568149": 1790243475,  # 17:51:15
    "7689003105328975156": 1790235552,  # 15:39:12
    "7688960000504368404": 1790225513,  # 12:51:53
}
YESTERDAY_09_23 = {
    "7688685565037890836": 1790161614,  # 19:06:54
    "7688664034932952340": 1790156601,  # 17:43:21
}


def make_item(video_id, create_time, username="demo_alpha", desc="test video"):
    return {
        "id": video_id,
        "createTime": create_time,
        "desc": desc,
        "author": {"uniqueId": username},
        "video": {"id": video_id},
        "stats": {"diggCount": 0},
    }


def make_item_list(items):
    """构造 item_list 响应体 JSON 字符串。"""
    return json.dumps({
        "cursor": "0",
        "hasMore": True,
        "itemList": items,
        "statusCode": 0,
    })


def today_items():
    return [make_item(vid, ct) for vid, ct in TODAY_09_24.items()]


def yesterday_items():
    return [make_item(vid, ct) for vid, ct in YESTERDAY_09_23.items()]


def today_plus_yesterday_items():
    """今日 4 条 + 昨日 2 条，按时间倒序（最新在前）。"""
    all_items = list(TODAY_09_24.items()) + list(YESTERDAY_09_23.items())
    all_items.sort(key=lambda kv: kv[1], reverse=True)
    return [make_item(vid, ct) for vid, ct in all_items]

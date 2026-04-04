import asyncio
import json
import websockets
from datetime import datetime
import requests
import time

WS_URL = "wss://ws-subscriptions-frontend-clob.polymarket.com/ws/market"
MARKET_URL = f"https://gamma-api.polymarket.com/markets/slug/"

async def get_asset_ids(slug) -> list[str]:
    # 获取事件循环
    loop = asyncio.get_event_loop()
    # 在异步线程中执行 requests（不阻塞事件循环）
    resp = await loop.run_in_executor(
        None,
        requests.get,
        MARKET_URL + slug
    )
    # 获取数据
    data = resp.json()
    # 提取并安全解析（替换危险的 eval）
    ids_raw = data.get("clobTokenIds", "[]")
    asset_ids = json.loads(ids_raw)

    return asset_ids


async def subscribe_orderbook():
    now = int(time.time() // 300 * 300)
    event_slug = "btc-updown-5m-%s" % now    # 当前想监控的市场 slug
    asset_ids = await get_asset_ids(event_slug)

    async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=10) as ws:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 已连接 CLOB Market WebSocket")

        while True:
            # 订阅消息（官方推荐格式）
            sub_msg = {
                "assets_ids": asset_ids,          # 必须传两个 token id（Up + Down）
                "type": "market",
                "custom_feature_enabled": True
            }

            await ws.send(json.dumps(sub_msg))
            print(f"已订阅订单簿，slug: {event_slug} asset_ids: {asset_ids[:2]}...")

            async for message in ws:
                # 判断是否结束，开始新的订阅
                new_slug_time = int(time.time() // 300 * 300)
                if new_slug_time > now:
                    now = new_slug_time
                    event_slug = "btc-updown-5m-%s" % new_slug_time
                    print(f"⏰ 切换到新的 slug: {event_slug}")
                    break
                try:
                    data = json.loads(message)
                    msg_type = data.get("event_type")

                    if msg_type == "price_change":
                        items = data.get('price_changes', [])
                        for item in items:
                            price = item.get('price')
                            size = item.get('size')
                            side = item.get('side')
                            print(f"🔄 最新成交价: {price}, 量: {size}, 方向: {side}")
                    # else:
                    #     # 可注释掉，避免刷屏
                    #     print(f"其他消息: {msg_type}")

                except Exception as e:
                    print("解析错误:", e)

if __name__ == "__main__":
    asyncio.run(subscribe_orderbook())

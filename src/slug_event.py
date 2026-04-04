import asyncio
import json
import websockets
from datetime import datetime
import time

DATA_URL = "wss://ws-live-data.polymarket.com"

async def activity_stream():
    now = int(time.time() // 300 * 300)
    event_slug = "btc-updown-5m-%s" % now    # 当前想监控的市场 slug

    async with websockets.connect(DATA_URL, ping_interval=5, ping_timeout=10) as ws:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 已连接")

        # 循环发送订阅消息，保持连接
        while True:
            # 订阅 orders_matched（成交记录）
            subscribe_msg = {
                "action": "subscribe",
                "subscriptions": [
                    {
                        "topic": "activity",
                        "type": "orders_matched",
                        "filters": json.dumps({"event_slug": event_slug}, separators=(",", ":"))
                    }
                ]
            }
            await ws.send(json.dumps(subscribe_msg))
            print(f"已订阅 activity / orders_matched → {event_slug}")

            async for message in ws:
                # 判断是否结束，开始新的订阅
                new_slug_time = int(time.time() // 300 * 300)
                if new_slug_time > now:
                    now = new_slug_time
                    event_slug = "btc-updown-5m-%s" % new_slug_time
                    print(f"⏰ 切换到新的 slug: {event_slug}")
                    break
                if message.strip().lower() in ["pong", "ping", ""]:
                    continue

                try:
                    data = json.loads(message)
                    if data.get("topic") == "activity" and data.get("type") == "orders_matched":
                        payload = data.get("payload", {})
                        side = payload.get("side")
                        size = payload.get("size")
                        price = payload.get("price")
                        outcome = payload.get("outcome")
                        ts = data.get("timestamp")

                        dt = datetime.fromtimestamp(ts / 1000) if ts else datetime.now()
                        print(f"📊 {dt.strftime('%H:%M:%S')} | {side:4} {size:8.2f} @ ${price:.4f} | {outcome} | {payload.get('title','')}")
                except Exception as e:
                    pass  # 忽略解析错误

asyncio.run(activity_stream())

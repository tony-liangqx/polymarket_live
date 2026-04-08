import asyncio
import json
import websockets
from datetime import datetime, timezone
import requests
import time
import aiohttp

WS_URL = "wss://ws-subscriptions-frontend-clob.polymarket.com/ws/market"
MARKET_URL = f"https://gamma-api.polymarket.com/markets/slug/"
OPEN_PRICE_URL_TEMPLATE = "https://polymarket.com/api/crypto/crypto-price?symbol=BTC&eventStartTime=%s&variant=fiveminute&endDate=%s"

PriceLock = asyncio.Lock()
global_btc_price = 0
# 5m
Interval = 300

async def fetch_get(url_template, star_time, end_time):
    start_utc_time = datetime.fromtimestamp(star_time, timezone.utc).isoformat().replace("+00:00", "Z")
    end_utc_time = datetime.fromtimestamp(end_time, timezone.utc).isoformat().replace("+00:00", "Z")
    url = url_template % (start_utc_time, end_utc_time)
    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.get(url) as response:
            data = await response.json()
            return data.get("openPrice")

async def btc_price_stream():
    url = "wss://ws-live-data.polymarket.com"

    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=120) as ws:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 已连接到 RTDS")

                # 最安全的订阅方式：不带 filters（订阅所有 crypto_prices）
                subscribe_msg = {
                    "action": "subscribe",
                    "subscriptions": [
                        {
                            "topic": "crypto_prices",
                            "type": "update"
                            # 不写 filters 字段，或写 "filters": ""
                        }
                    ]
                }

                await ws.send(json.dumps(subscribe_msg))
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 已发送订阅（所有 crypto_prices）")

                # 心跳
                async def heartbeat():
                    while True:
                        await asyncio.sleep(5)
                        # if not ws.closed:
                        await ws.send("ping")

                ping_task = asyncio.create_task(heartbeat())

                print("正在等待数据...（会收到很多交易对的价格，请耐心等几秒）\n")

                async for message in ws:
                    if not message or message.strip().lower() in ["pong", "ping", ""]:
                        continue

                    try:
                        data = json.loads(message)

                        if data.get("topic") == "crypto_prices":
                            payload = data.get("payload") or data
                            symbol = payload.get("symbol", "").upper()
                            price = payload.get("value") or payload.get("price")
                            ts = payload.get("timestamp") or data.get("timestamp")

                            if price and "BTC" in symbol:
                                dt = datetime.fromtimestamp(ts / 1000) if isinstance(ts, (int, float)) else datetime.now()
                                #print(f"🟢 {dt.strftime('%H:%M:%S.%f')[:-3]} | BTC 价格: ${float(price):,.2f}   (symbol: {symbol})")
                                async with PriceLock:
                                    global global_btc_price
                                    global_btc_price = float(price)
                            # else:
                            #     print(f"其他价格: {symbol} = {price}")  # 调试时可取消注释看流量
                    except json.JSONDecodeError:
                        pass
                    except Exception as e:
                        print(f"解析异常: {e}")

                await ping_task

        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 连接异常: {e}，5秒后重连...")
            await asyncio.sleep(5)

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


# ========== 带超时的接收 ==========
async def receive_with_timeout(websocket, timeout):
    # await 加上超时
    message = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    return json.loads(message)


async def subscribe_orderbook():
    start_time = int(time.time() // Interval * Interval)
    event_slug = "btc-updown-5m-%s" % start_time    # 当前想监控的市场 slug
    asset_ids = await get_asset_ids(event_slug)
    open_price = await fetch_get(OPEN_PRICE_URL_TEMPLATE, start_time, start_time+300)

    async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=120) as ws:
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

            # 去重寄存器
            timestamp = 0
            while True:
                now = int(time.time())
                timeout = (start_time + Interval) - now
                if timeout < 1:
                    # 下一轮
                    # 判断是否结束，开始新的订阅
                    start_time = int(now // Interval * Interval)
                    event_slug = "btc-updown-5m-%s" % start_time
                    open_price = await fetch_get(OPEN_PRICE_URL_TEMPLATE, start_time, start_time+300)
                    print(f"⏰ 切换到新的 slug: {event_slug}")
                    break
                try:
                    data = await receive_with_timeout(ws, timeout)
                except (asyncio.TimeoutError, json.decoder.JSONDecodeError):
                    continue

            # async for message in ws:
                # # 判断是否结束，开始新的订阅
                # new_slug_time = int(time.time() // 300 * 300)
                # if new_slug_time > start_time:
                #     start_time = new_slug_time
                #     event_slug = "btc-updown-5m-%s" % new_slug_time
                #     open_price = await fetch_get(OPEN_PRICE_URL_TEMPLATE, start_time, start_time+300)
                #     print(f"⏰ 切换到新的 slug: {event_slug}")
                #     break
                try:
                    # data = json.loads(message)
                    msg_type = data.get("event_type")
                    if msg_type == "price_change":
                        items = data.get('price_changes', [])
                        for item in items:
                            ts = int(data.get('timestamp')) // 1000
                            # 去重: 只取一个点
                            if ts == timestamp:
                                continue
                            timestamp = ts
                            # price = item.get('price')
                            # size = item.get('size')
                            # side = item.get('side')
                            best_bid = item.get("best_bid")
                            best_ask = item.get("best_ask")
                            async with PriceLock:
                                btc_price = global_btc_price
                            if btc_price == 0:
                                continue

                            print(f"now: {timestamp} start: {start_time} end: {start_time + Interval} open: {open_price} price: {btc_price} best_bid:{best_bid} best_ask: {best_ask}")
                    # else:
                    #     # 可注释掉，避免刷屏
                    #     print(f"其他消息: {msg_type}")

                except Exception as e:
                    print("解析错误:", e)

if __name__ == "__main__":
    async def main():
        # 同时并发运行多个任务
        await asyncio.gather(
            subscribe_orderbook(),
            btc_price_stream(),
        )
    asyncio.run(main())

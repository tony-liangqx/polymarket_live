import asyncio
import json
import websockets
from datetime import datetime, timezone
import requests
import time
import aiohttp

WS_URL = "wss://ws-subscriptions-frontend-clob.polymarket.com/ws/market"
MARKET_URL = f"https://gamma-api.polymarket.com/markets/slug/"
OPEN_PRICE_URL_TEMPLATE = "https://polymarket.com/api/crypto/crypto-price?symbol=%s&eventStartTime=%s&variant=%s&endDate=%s"


# 5m
Interval_5m = 300

class TaskOption(object):
    def __init__(self, interval: int, symbol: str):
        self.interval = interval
        self.symbol = symbol
        self.price = 0
        if interval == 300:
            self.event_slug = f"{symbol.lower()}-updown-5m-%s"
            self.variant="fiveminute"
        elif interval == 900:
             self.event_slug = f"{symbol.lower()}-updown-15m-%s"
             self.variant="fiveminute"

    def getTime(self) -> tuple[int, int]:
        start_time = int(time.time() // self.interval * self.interval)
        return start_time, start_time + self.interval

    def getOpenPriceUrl(self) -> str:
        start_time, end_time = self.getTime()
        start_utc_time = datetime.fromtimestamp(start_time, timezone.utc).isoformat().replace("+00:00", "Z")
        end_utc_time = datetime.fromtimestamp(end_time, timezone.utc).isoformat().replace("+00:00", "Z")
        return OPEN_PRICE_URL_TEMPLATE % (self.symbol, start_utc_time, self.variant, end_utc_time)

    def getSlug(self) -> str:
        start_time, _ = self.getTime()
        return self.event_slug % (start_time,)

    def getPrice(self) -> float:
        return self.price

    def updatePrice(self, price:float):
        self.price = price

    def getSymbol(self) -> str:
        return self.symbol

async def fetch_open_price(url):
    while True:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(3)) as session:
            async with session.get(url) as response:
                data = await response.json()
                price = data.get("openPrice")
                if price is None:
                    print(url, json.dumps(data))
                    await asyncio.sleep(1)
                    continue
                return data.get("openPrice")

async def btc_price_stream(option: TaskOption):
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

                            if price and option.getSymbol() in symbol:
                                option.updatePrice(float(price))
                            # else:
                            #     print(f"其他价格: {symbol} = {price}")  # 调试时可取消注释看流量
                    except json.JSONDecodeError as e:
                        print(e)
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

async def subscribe_orderbook(option: TaskOption):
    # 网络重连循环
    while True:
        try:
            start_time, end_time = option.getTime()
            event_slug = option.getSlug()
            open_price_url = option.getOpenPriceUrl()

            asset_ids = await get_asset_ids(event_slug)
            open_price = await fetch_open_price(open_price_url)

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
                        timeout = end_time - now
                        if timeout < 1:
                            # 下一轮
                            # 判断是否结束，开始新的订阅
                            start_time, end_time = option.getTime()
                            event_slug = option.getSlug()
                            open_price_url = option.getOpenPriceUrl()
                            open_price = await fetch_open_price(open_price_url)
                            print(f"⏰ 切换到新的 slug: {event_slug}")
                            break
                        try:
                            data = await receive_with_timeout(ws, timeout)
                        except (asyncio.TimeoutError, json.decoder.JSONDecodeError) as e:
                            print(e)
                            continue
                        try:
                            msg_type = data.get("event_type")
                            if msg_type == "price_change":
                                items = data.get('price_changes', [])
                                for item in items:
                                    ts = int(data.get('timestamp')) // 1000
                                    # 去重: 只取一个点
                                    if ts == timestamp:
                                        continue
                                    timestamp = ts
                                    best_bid = item.get("best_bid")
                                    best_ask = item.get("best_ask")
                                    price = option.getPrice()
                                    if price == 0:
                                        continue

                                    print(f"{timestamp} {option.getSymbol()} start: {start_time} end: {end_time} open: {open_price} price: {price} best_bid:{best_bid} best_ask: {best_ask}")

                        except Exception as e:
                            print("解析错误:", e)
        except Exception as e:
            print(e)



if __name__ == "__main__":
    async def main():
        # 同时并发运行多个任务
        btc5m = TaskOption(Interval_5m, "BTC")
        eth5m = TaskOption(Interval_5m, "ETH")
        await asyncio.gather(
            subscribe_orderbook(btc5m),
            btc_price_stream(btc5m),
            subscribe_orderbook(eth5m),
            btc_price_stream(eth5m),
        )
    asyncio.run(main())

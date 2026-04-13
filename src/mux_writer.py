import asyncio
import json
import websockets
from datetime import datetime, timezone
from typing import Optional
import time
import aiohttp
import logging

# 基础配置（输出级别、格式）
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.DEBUG  # 开启 DEBUG 级别日志
)
logging.getLogger("websockets").setLevel(logging.WARNING)

WS_URL = "wss://ws-live-data.polymarket.com/"
OPEN_PRICE_URL_TEMPLATE = "https://polymarket.com/api/crypto/crypto-price?symbol=%s&eventStartTime=%s&variant=%s&endDate=%s"


# 5m
Interval_5m = 300
Interval_15m = 900
Interval_day = 86400

# type: ignore
HTTP_SESSION: Optional[aiohttp.ClientSession] = None

class SymbolPrice(object):
    def __init__(self, *symbs:str):
        self.symbols = {}
        for symb in symbs:
            self.symbols[symb+"USDT"] = 0

    def updatePrice(self, symbol: str, price:float):
        self.symbols[symbol] = price

    def getPrice(self, symbol: str):
        return self.symbols[symbol+"USDT"]

    def getSymbols(self):
        return self.symbols.keys()

class TaskOption(object):
    def __init__(self, interval: int, symbol: str):
        self.interval = interval
        self.symbol = symbol
        self.topic = "crypto_prices_chainlink"

        if interval == Interval_5m:
           self.event_slug = f"{symbol.lower()}-updown-5m-%s"
           self.variant="fiveminute"
        elif interval == Interval_15m:
            self.event_slug = f"{symbol.lower()}-updown-15m-%s"
            self.variant="fifteen"
        elif interval == Interval_day:
            if symbol == "BTC":
                self.event_slug = f"bitcoin-up-or-down-on-%s"
            elif symbol == "ETH":
                self.event_slug = f"ethereum-up-or-down-on-%s"
            else:
                self.event_slug = f"{symbol.lower()}-up-or-down-on-%s"
            self.variant="daily"
            self.topic = "crypto_prices"
        else:
            raise Exception("interval type error")

    def getTopic(self) -> str:
        return self.topic

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
        if self.interval == Interval_day:
            # 特殊格式
            # "bitcoin-up-or-down-on-april-9-2026"
            # "ethereum-up-or-down-on-april-8-2026"
            date_str = datetime.fromtimestamp(start_time).strftime("%B-%d-%Y").lower().replace("-0", "-")
            return self.event_slug % (date_str,)
        return self.event_slug % (start_time,)

    def getSymbol(self) -> str:
        return self.symbol

    def getFullSymbol(self) -> str:
        if self.interval == Interval_day:
            return self.symbol + "USDT"
        return self.symbol.lower() + "/usd"

async def fetch_open_price(url):
    global HTTP_SESSION
    if HTTP_SESSION is None:
            HTTP_SESSION = aiohttp.ClientSession(
                trust_env=True,
                timeout=aiohttp.ClientTimeout(3)
            )
    while True:
        async with HTTP_SESSION.get(url) as response:
            data = await response.json()
            price = data.get("openPrice")
            if price is None:
                logging.debug(f"{url}, {data}")
                await asyncio.sleep(1)
                continue
            return data.get("openPrice")


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
            open_price = await fetch_open_price(open_price_url)

            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=120) as ws:
                logging.debug(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 已连接 CLOB Market WebSocket")

                while True:
                    # 订阅消息（官方推荐格式）
                    sub_msg = {
                        "action": "subscribe",
                        "subscriptions": [
                            {
                                "topic": "activity",
                                "type": "orders_matched",
                                "filters": "{\"event_slug\":\"%s\"}" % (event_slug,)
                            },
                            {
                                "topic": option.getTopic(),
                                "type": "update",
                                "filters": "{\"symbol\":\"%s\"}" % (option.getFullSymbol(),)
                            }
                        ]
                    }
                    print(json.dumps(sub_msg))

                    await ws.send(json.dumps(sub_msg))
                    logging.debug(f"已订阅订单簿，slug: {event_slug}, open price: {open_price}")

                    # 去重寄存器
                    coin_price = 0
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
                            logging.debug(f"⏰ 切换到新的 slug: {event_slug}")
                            break
                        try:
                            data = await receive_with_timeout(ws, timeout)
                            outcome = "-"
                            order_price = "-"
                            side = "-"
                            size = "-"
                            msg_type = data.get("type")
                            if msg_type == "update":
                                payload = data.get("payload")
                                if payload is None:
                                    continue
                                coin_price = payload.get("value")
                            elif msg_type == "orders_matched":
                                # 没有价格，忽略订单信息
                                if coin_price == 0:
                                    continue
                                payload = data.get("payload")
                                if payload is None:
                                    continue
                                outcome = payload.get("outcome")
                                order_price = payload.get("price")
                                side = payload.get("side")
                                size = payload.get("size")
                            else:
                                continue
                            timestamp = payload.get("timestamp")
                            print(f"{timestamp} {option.getSymbol()} {option.variant} start: {start_time} end: {end_time} open: {open_price} coin_price: {coin_price} {outcome} {side} {size} order_price: {order_price}")
                        except (asyncio.TimeoutError, json.decoder.JSONDecodeError):
                            logging.debug("receive_with_timeout 发生异常:", exc_info=True)
                            continue
                        except websockets.exceptions.ConnectionClosedError as e:
                            raise e
                        except Exception:
                            logging.debug("data 发生异常:", exc_info=True)
        except Exception:
            logging.debug("subscribe_orderbook 发生异常:", exc_info=True)



if __name__ == "__main__":
    async def main():
        btc5m = TaskOption(Interval_5m, "BTC")
        btc15m = TaskOption(Interval_15m, "BTC")
        btcday = TaskOption(Interval_day, "BTC")

        eth5m = TaskOption(Interval_5m, "ETH")
        eth15m = TaskOption(Interval_15m, "ETH")
        ethday = TaskOption(Interval_day, "ETH")

        sol5m = TaskOption(Interval_5m, "SOL")
        sol15m = TaskOption(Interval_15m, "SOL")

        xrp5m = TaskOption(Interval_5m, "XRP")
        xrp15m = TaskOption(Interval_15m, "XRP")

        doge5m = TaskOption(Interval_5m, "DOGE")
        doge15m = TaskOption(Interval_15m, "DOGE")

        # 同时并发运行多个任务
        await asyncio.gather(
            # BTC
            subscribe_orderbook(btc5m),
            # subscribe_orderbook(btc15m),
            # subscribe_orderbook(btcday),

            # # eth
            # subscribe_orderbook(eth5m),
            # subscribe_orderbook(eth15m),
            # subscribe_orderbook(ethday),

            # # # sol
            # subscribe_orderbook(sol5m),
            # subscribe_orderbook(sol15m),

            # # # xrp
            # subscribe_orderbook(xrp5m),
            # subscribe_orderbook(xrp15m),

            # # doge
            # subscribe_orderbook(doge5m),
            # subscribe_orderbook(doge15m),
        )
    asyncio.run(main())

import asyncio
import json
from web3.types import Timestamp
import websockets
from datetime import datetime, timezone
from typing import Optional
import time
import aiohttp
import logging
import asyncio
import paho.mqtt.client as mqtt
import time
from paho.mqtt.enums import CallbackAPIVersion
from py_clob_client.clob_types import OrderArgs, OrderType
import setting


# 配置
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC_DATA = "data/topic"
MQTT_TOPIC_COMPUTE = "compute/topic"
MQTT_CLIENT_ID = "data_unit"

# 基础配置（输出级别、格式）
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.DEBUG  # 开启 DEBUG 级别日志
)
logging.getLogger("websockets").setLevel(logging.WARNING)
# 关闭所有日志输出
logging.disable(logging.CRITICAL + 1)

WS_URL = "wss://ws-live-data.polymarket.com/"
MARKET_WS_URL = "wss://ws-subscriptions-frontend-clob.polymarket.com/ws/market"
MARKET_URL = f"https://gamma-api.polymarket.com/markets/slug/"
OPEN_PRICE_URL_TEMPLATE = "https://polymarket.com/api/crypto/crypto-price?symbol=%s&eventStartTime=%s&variant=%s&endDate=%s"


# 5m
Interval_5m = 300
Interval_15m = 900
Interval_day = 86400

#
# @price: 你愿意支付的价格
# @size: 买入数量
#
def Buy(token_id: str, price: float, size: float):
    buy_order_args = OrderArgs(
        price=price, # 你愿意支付的价格
        size=size,  # 买入数量
        side="BUY",
        token_id=token_id
    )
    signed_order = setting.TRADE_CLIENT.create_order(buy_order_args)
    resp = setting.TRADE_CLIENT.post_order(signed_order, orderType=OrderType.GTC) # type: ignore
    return resp


def Cancel():
    return setting.TRADE_CLIENT.cancel_all()

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
    def __init__(self, interval: int, symbol: str, mq_client: mqtt.Client):
        self.interval = interval
        self.symbol = symbol
        self.topic = "crypto_prices_chainlink"
        self.mq_client = mq_client
        self.order_time = 0

        # cache
        self.cache = {"SLEE": (0, "", ""), "BUY": (0, "", "")}

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

    def setValue(self, timestamp, side, bid, ask):
        self.cache[side] = (timestamp, bid, ask)

    def getValue(self, side) -> tuple[int, str, str]:
        return self.cache[side]

    def getKey(self) -> str:
        variant: str
        if self.variant == "fiveminute":
            variant  = "5m"
        elif self.variant == "fifteen":
            variant = "15m"
        elif self.variant == "daily":
            variant = "1d"
        else:
            raise Exception("interval type error")
        return self.symbol + "USDT" + variant

    def setOrderTime(self, timestamp: int):
        self.order_time = timestamp

    def getOrderTime(self) -> int:
        return self.order_time

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
                            if order_price == "-":
                                continue
                            ts, bid, ask = option.getValue(side)
                            if timestamp - ts > 1:
                                bid = "NaN"
                                ask = "NaN"
                            # 统一名称
                            if side == "BUY":
                                side = "Up"
                            elif side == "SELL":
                                side = "Down"
                            msg = f"current: {timestamp} symbol: {option.getSymbol()} variant: {option.variant} start: {start_time} end: {end_time} open: {open_price} coin_price: {coin_price} direction: {side} bid: {bid} ask: {ask}"
                            option.mq_client.publish(
                                # 写给 计算进程
                                topic=MQTT_TOPIC_COMPUTE,
                                payload=msg,
                                qos=0
                            )
                        except (asyncio.TimeoutError, json.decoder.JSONDecodeError):
                            logging.debug("receive_with_timeout 发生异常:", exc_info=True)
                            continue
                        except websockets.exceptions.ConnectionClosedError as e:
                            raise e
                        except Exception:
                            logging.debug("data 发生异常:", exc_info=True)
        except Exception:
            logging.debug("subscribe_orderbook 发生异常:", exc_info=True)

async def get_asset_ids(slug) -> list[str]:
    global HTTP_SESSION
    if HTTP_SESSION is None:
            HTTP_SESSION = aiohttp.ClientSession(
                trust_env=True,
                timeout=aiohttp.ClientTimeout(3)
            )
    url = MARKET_URL + slug
    while True:
        try:
            async with HTTP_SESSION.get(url) as resp:
                data = await resp.json()
                ids_raw = data.get("clobTokenIds")
                if ids_raw is None:
                    await asyncio.sleep(1)
                    continue
                asset_ids = json.loads(ids_raw)
                return asset_ids
        except Exception:
            logging.debug(f"fetch {url} error")
            raise Exception(f"fetch {url} error")

async def subscribe_asset_ids(option: TaskOption):
    # 网络重连循环
    while True:
        try:
            _, end_time = option.getTime()
            event_slug = option.getSlug()

            asset_ids = await get_asset_ids(event_slug)
            updown = {asset_ids[0]: "Up", asset_ids[1]: "Down"}

            async with websockets.connect(MARKET_WS_URL, ping_interval=20, ping_timeout=120) as ws:
                logging.debug(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ 已连接 CLOB Market WebSocket")

                while True:
                    # 订阅消息（官方推荐格式）
                    sub_msg = {
                        "assets_ids": asset_ids,          # 必须传两个 token id（Up + Down）
                        "type": "market",
                        "custom_feature_enabled": True
                    }

                    await ws.send(json.dumps(sub_msg))
                    logging.debug(f"已订阅订单簿，slug: {event_slug} asset_ids: {asset_ids[:2]}...")

                    while True:
                        now = int(time.time())
                        timeout = end_time - now
                        if timeout < 1:
                            # 下一轮
                            # 判断是否结束，开始新的订阅
                            event_slug = option.getSlug()
                            logging.debug(f"⏰ 切换到新的 slug: {event_slug}")
                            break
                        try:
                            data = await receive_with_timeout(ws, timeout)
                        except (asyncio.TimeoutError, json.decoder.JSONDecodeError):
                            logging.debug("receive_with_timeout 发生异常:", exc_info=True)
                            continue
                        try:
                            if not isinstance(data, dict):
                                continue
                            msg_type = data.get("event_type")
                            if msg_type == "best_bid_ask":
                                timestamp = data.get('timestamp')
                                symb = option.getSymbol()
                                best_bid = data.get("best_bid")
                                best_ask = data.get("best_ask")
                                spread = data.get("spread")
                                asset_id = data.get("asset_id", "")
                                director = updown.get(asset_id)
                                msg = f"type: order current: {now} timestamp: {timestamp} symbol: {symb} {option.variant} direction: {director} spread: {spread} bid: {best_bid} ask: {best_ask}"
                                option.mq_client.publish(
                                    # 写给 计算进程
                                    topic=MQTT_TOPIC_COMPUTE,
                                    payload=msg,
                                    qos=0
                                )
                                continue
                            if msg_type == "price_change":
                                items = data.get('price_changes', [])
                                for item in items:
                                    timestamp = data.get('timestamp')
                                    if timestamp is None:
                                        continue
                                    timestamp = int(timestamp) // 1000
                                    side = item.get("side")
                                    best_bid = item.get("best_bid")
                                    best_ask = item.get("best_ask")
                                    option.setValue(timestamp, side, best_bid, best_ask)
                        except Exception:
                            logging.debug("data 发生异常:", exc_info=True)
        except Exception:
            logging.debug("subscribe_asset_ids 发生异常:", exc_info=True)


# 回调
def on_connect(client, userdata, flags, rc, properties=None):
    print(f"连接成功，code: {rc}")
    client.subscribe(MQTT_TOPIC_DATA)


def get_on_message_func(options: dict[str, TaskOption]):
    # 计算单元推送的信息
    def on_message(client, userdata, msg):
        print(f"\n主题: {msg.topic}")
        print(f"收到消息: {msg.payload.decode('utf-8')}")
        # TODO:: 接受的信息中需要携带 slug 信息
        # {"timestamp": 1776233693000, "prob_up": 0.5, "prob_down": 0.5, "symbol": "BTCUSDT", "interval": "5m/15m/1d", "bid": float, "ask": float, "direction": "Up/Down"}
        data = json.loads(msg.payload.decode('utf-8'))
        timestamp = data.get("timestamp", None)
        if timestamp is None:
            return
        symbol = data.get("symbol", None)
        if symbol is None:
            return
        interval = data.get("interval", None)
        if interval is None:
            return
        bid = data.get("bid", None)
        if bid is None:
            return
        ask = data.get("ask", None)
        if ask is None:
            return
        direction = data.get("direction", None)
        if direction is None:
            return
        slug = f"{symbol}{interval}"
        option = options.get(data["slug"], None)
        if option is None:
            logging.debug(f"om_message: 未知slug: {slug}")
            return
        last_order_time = option.getOrderTime()
        option.setOrderTime(timestamp)
        if last_order_time + 1000 < timestamp:
            return
        # TODO::
        # Cancel()
        # Buy(token_id: str, price: float, size: float)
        print("post action")

if __name__ == "__main__":
    async def main():
        client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=MQTT_CLIENT_ID
        )

        btc5m = TaskOption(Interval_5m, "BTC", client)
        # btc15m = TaskOption(Interval_15m, "BTC", client)
        # btcday = TaskOption(Interval_day, "BTC", client)

        # eth5m = TaskOption(Interval_5m, "ETH")
        # eth15m = TaskOption(Interval_15m, "ETH")
        # ethday = TaskOption(Interval_day, "ETH")

        # sol5m = TaskOption(Interval_5m, "SOL")
        # sol15m = TaskOption(Interval_15m, "SOL")

        # xrp5m = TaskOption(Interval_5m, "XRP")
        # xrp15m = TaskOption(Interval_15m, "XRP")

        # doge5m = TaskOption(Interval_5m, "DOGE")
        # doge15m = TaskOption(Interval_15m, "DOGE")

        task_options = {
            btc5m.getKey(): btc5m,
            # btc15m.getKey(): btc15m,
            # btcday.getKey(): btcday,
        }

        client.on_connect = on_connect
        client.on_message = get_on_message_func(task_options)

        # ✅ 异步连接（不阻塞）
        client.connect_async(MQTT_BROKER, MQTT_PORT)
        client.loop_start()

        # 同时并发运行多个任务
        await asyncio.gather(
            # BTC
            subscribe_orderbook(btc5m),
            subscribe_asset_ids(btc5m),
            # subscribe_orderbook(btc15m),
            # subscribe_asset_ids(btc15m),
            # subscribe_orderbook(btcday),
            # subscribe_asset_ids(btcday),

            # # eth
            # subscribe_orderbook(eth5m),
            # subscribe_orderbook(eth15m),
            # subscribe_orderbook(ethday),

            # # sol
            # subscribe_orderbook(sol5m),
            # subscribe_orderbook(sol15m),

            # # xrp
            # subscribe_orderbook(xrp5m),
            # subscribe_orderbook(xrp15m),

            # # doge
            # subscribe_orderbook(doge5m),
            # subscribe_asset_ids(doge5m),
            # subscribe_orderbook(doge15m),
        )
    asyncio.run(main())

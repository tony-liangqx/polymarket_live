import asyncio
import json
import websockets
from datetime import datetime

async def btc_price_stream():
    url = "wss://ws-live-data.polymarket.com"

    while True:
        try:
            async with websockets.connect(url, ping_interval=5, ping_timeout=10) as ws:
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
                                print(f"🟢 {dt.strftime('%H:%M:%S.%f')[:-3]} | BTC 价格: ${float(price):,.2f}   (symbol: {symbol})")
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

if __name__ == "__main__":
    try:
        asyncio.run(btc_price_stream())
    except KeyboardInterrupt:
        print("\n\n👋 已停止")

import asyncio
import json
import math
import time

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from get_selling_permission import get_selling_permission
from redis_prediction_client import get_volatility_prediction

# 配置
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC_DATA = "data/topic"
MQTT_TOPIC_COMPUTE = "compute/topic"
MQTT_CLIENT_ID = "compute_unit"
latest_params = {}


# 回调
def on_connect(client, userdata, flags, rc, properties=None):
    print(f"连接成功，code: {rc}")
    client.subscribe(MQTT_TOPIC_COMPUTE)


def on_message(client, userdata, msg):
    global latest_params
    latest_params = json.loads(msg.payload.decode("utf-8"))
    print("收到参数:", latest_params)


def compute_signal():
    global latest_params
    volatility_prediction = get_volatility_prediction()
    selling_permission = get_selling_permission()
    print("当前参数:", latest_params)
    symbol = "BTCUSDT"
    direction = latest_params.get("direction", None)
    best_bid = latest_params.get("bid", 0)
    best_ask = latest_params.get("ask", 0)
    spread = latest_params.get("spread", 0)
    quote_ask = best_ask - 0.1 * (spread > 0.1)
    end_time = latest_params.get("end", 0)
    current_price = latest_params.get("coin_price", 0)
    open_price = latest_params.get("open", 0)
    interval = latest_params.get("variant", None)
    interval = '5m'
    remaining_seconds = end_time - int(time.time())
    volatility_predict = volatility_prediction.get(symbol, None)
    log_return_now = math.log(current_price / open_price)
    time_scale = remaining_seconds / 300.0
    vol_remaining = volatility_predict * math.sqrt(time_scale)
    if vol_remaining <= 0:
        return {}
    z = log_return_now / vol_remaining
    prob_up = 0.5 * (1.0 + math.erf(z / math.sqrt(2)))
    fair_price = {'Up': prob_up, 'Down': 1 - prob_up}
    if selling_permission.get(direction, False) and quote_ask >= fair_price[direction]:
        return {"timestamp": int(time.time_ns() / 1000000), "price": quote_ask, "symbol": symbol, "interval": interval,
                "bid": None, "ask": quote_ask,
                "direction": direction}
    else:
        return {}


def on_publish(client, userdata, mid):
    print(f"消息已发送: {mid}")


async def main():
    # 创建客户端
    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=MQTT_CLIENT_ID
    )

    client.on_connect = on_connect
    client.on_message = on_message

    # 异步连接
    client.connect_async(MQTT_BROKER, MQTT_PORT)
    client.loop_start()

    # 等待连接成功
    await asyncio.sleep(0.3)

    while True:
        msg = compute_signal()

        client.publish(
            topic=MQTT_TOPIC_DATA,
            payload=json.dumps(msg),
            qos=0
        )



        # print(f"✅ 消息已发送：{msg}")
        await asyncio.sleep(2)

    # # 停止并断开
    # client.loop_stop()
    # client.disconnect()


if __name__ == "__main__":
    main()

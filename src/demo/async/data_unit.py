import asyncio
import paho.mqtt.client as mqtt
import time
from paho.mqtt.enums import CallbackAPIVersion

# 配置
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC_DATA = "data/topic"
MQTT_TOPIC_COMPUTE = "compute/topic"
MQTT_CLIENT_ID = "data_unit"

# 回调
def on_connect(client, userdata, flags, rc, properties=None):
    print(f"连接成功，code: {rc}")
    client.subscribe(MQTT_TOPIC_DATA)

def on_message(client, userdata, msg):
    # print(f"\n[异步订阅] 主题: {msg.topic}")
    print(f"收到消息: {msg.payload.decode('utf-8')}")

async def main():
    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=MQTT_CLIENT_ID
    )

    client.on_connect = on_connect
    client.on_message = on_message

    # ✅ 异步连接（不阻塞）
    client.connect_async(MQTT_BROKER, MQTT_PORT)
    client.loop_start()

    # 保持异步事件循环运行
    while True:
        # 异步发布消息
        msg = f"数据进程 推送 {time.time()}"
        info = client.publish(
            # 写给 计算进程
            topic=MQTT_TOPIC_COMPUTE,
            payload=msg,
            qos=0
        )

        # print(f"✅ 消息已发送：{msg}")
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())

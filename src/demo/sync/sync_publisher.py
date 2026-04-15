import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
import time

# ===================== 配置 =====================
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "test/topic"
MQTT_CLIENT_ID = "python_publisher"

# 发布函数
def publish_message(message):
    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=MQTT_CLIENT_ID)
    client.connect(MQTT_BROKER, MQTT_PORT, 60)

    # 发布：主题 + 消息内容
    result = client.publish(MQTT_TOPIC, message)

    # 检查是否发布成功
    status = result[0]
    if status == 0:
        print(f"成功发送：{message} 到主题：{MQTT_TOPIC} {time.time()}")
    else:
        print("发送失败")

    client.disconnect()

# ===================== 测试发送 =====================
if __name__ == "__main__":
    while True:
        publish_message("Hello Mosquitto! 这是一条测试消息")
        time.sleep(5)

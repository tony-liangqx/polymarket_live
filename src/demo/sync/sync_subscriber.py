import paho.mqtt.client as mqtt
# 从这里导入，就不会报私有导入错误
from paho.mqtt.enums import CallbackAPIVersion

# 配置
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "test/topic"
MQTT_CLIENT_ID = "python_subscriber"

# 连接回调（新版 5 个参数）
def on_connect(client, userdata, flags, rc, properties=None):
    print("连接成功，code:", rc)
    client.subscribe(MQTT_TOPIC)

# 消息回调
def on_message(client, userdata, msg):
    print(f"\n收到：{msg.topic} -> {msg.payload.decode()}")

# ✅ 关键：必须指定 callback_api_version=VERSION2
client = mqtt.Client(
    callback_api_version=CallbackAPIVersion.VERSION2,
    client_id=MQTT_CLIENT_ID
)

client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.loop_forever()

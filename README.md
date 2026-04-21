# 依赖
## python库
```
pip install asyncio websockets requests py_clob_client paho-mqtt
```

## 中间件： mqtt
windows的安装：
```
官网下载页：https://mosquitto.org/download/
最新稳定版（2026-04）：
64 位：mosquitto-2.0.15-install-windows-x64.exe
32 位：mosquitto-2.0.15-install-windows-x32.exe
```

ubuntu的安装：
```
sudo apt-add-repository ppa:mosquitto-dev/mosquitto-ppa
sudo apt-get update
```

### mqtt的配置
linux常见配置路径`/etc/mosquitto/mosquitto.conf`
```
# 监听端口
listener 1883

# 最大连接数
max_connections 500

## 自动生成持久化文件（消息队列、订阅信息）
#persistence true
#persistence_file mosquitto.db
#persistence_location ./

# 日志输出
log_dest stdout
log_type error
log_type warning
log_type notice
log_type information

# 允许匿名访问（开发测试用，生产建议关闭）
allow_anonymous true

# 客户端心跳超时（秒）
#keepalive_interval 60

# 消息队列大小
max_inflight_messages 100
max_queued_messages 100
```

# 使用

## 具体一个盘的情况：slug_event.py

```
python3 src/slug_event.py
```

## 具体一个盘的订单：orderbooks.py

```
python3 src/orderbooks.py
```

## 订阅价格： price.py

```
python3 scr/price.py
```

# 通过消息broke隔离进程

`客户处理进程` 与 `数据服务进程` 通过消息队列通信，定义数据格式

## 数据服务 `==>` 客户处理
### 1、价格信息帧
```text
# 数据帧为纯文本（兼容v2的版本）
current: 1776233693 symbol: BTC variant: fiveminute start: 1776233400 end: 1776233700 open: 73971.8468 coin_price: 73993.99406730176 BUY_bid: NaN BUY_ask: NaN
```

### 2、盘口信息帧
```text
# 数据帧为纯文本
type: order current: 1776258251 timestamp: 1776258250933 symbol: BTC fiveminute up spread: 0.002 bid: 0.05 ask: 0.052
```

## 客户处理 `==>` 数据服务
### 订单任务帧
```text
{"timestamp": 1776233693000, "symbol": "BTCUSDT", "interval": "5m", "bid": 0.5, "ask": 0.5, "direction": "Up"}
```

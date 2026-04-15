# 依赖

```
pip install asyncio websockets requests
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
### 1、信息帧
```text
xxx
```

### 2、信息帧
```text
# 数据帧为纯文本
xxx
```

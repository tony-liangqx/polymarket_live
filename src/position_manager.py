#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
polymarket_position_module
2026/4/17 14:58
Author: Joyful_Flame_Finance
"""
import json
import time
import logging
import requests
from polymarket_apis import PolymarketGammaClient
from polymarket_apis.clients.web3_client import PolymarketGaslessWeb3Client
from py_clob_client.client import ClobClient
from pathlib import Path

# =========================
# logging 配置
# =========================
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "polymarket_position.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("PositionManager")

# =========================
# 1. 配置参数
# =========================
with open('metamask_dict.json', 'r') as f:
    METAMASK_DICT = json.load(f)
    PRIVATE_KEY = METAMASK_DICT['api_key']
    PROXY_WALLET_ADDRESS = METAMASK_DICT['proxy_wallet_address']

with open('relayer_dict.json', 'r') as f:
    RELAYER_API_DICT = json.load(f)

# =========================
# 初始化客户端
# =========================
POSITION_CLIENT = PolymarketGaslessWeb3Client(
    private_key=PRIVATE_KEY,
    signature_type=2,
    relayer_api_key=RELAYER_API_DICT['api_key'],
    chain_id=137,
    rpc_url="https://tenderly.rpc.polygon.community"
)

GAMMA_CLIENT = PolymarketGammaClient()

TEMP_CLIENT = ClobClient(
    "https://clob.polymarket.com",
    key=PRIVATE_KEY,
    chain_id=137
)

API_CREDS = TEMP_CLIENT.create_or_derive_api_creds()

TRADE_CLIENT = ClobClient(
    "https://clob.polymarket.com",
    key=PRIVATE_KEY,
    chain_id=137,
    creds=API_CREDS,
    signature_type=2,
    funder=PROXY_WALLET_ADDRESS
)

# =========================
# 策略参数
# =========================
FULL_POS_AMOUNT = 10.0
NEG_RISK = False
ADD_NEW_POSITION_THRESHOLD = 0.5
STOP_SELLING_THRESHOLD = 0.1


def split_position(condition_id, position_client=POSITION_CLIENT, split_amount=FULL_POS_AMOUNT):
    try:
        logger.info(f"开始拆分仓位 | condition_id={condition_id} | amount={split_amount}")
        receipt = position_client.split_position(
            condition_id=condition_id,
            amount=split_amount,
            neg_risk=NEG_RISK
        )
        logger.info("拆分成功")
        return receipt
    except Exception as e:
        logger.error(f"拆分失败 | condition_id={condition_id} | error={e}", exc_info=True)
        return None


def generate_current_slug(
    symbol='btc',
    interval='5m',
    timestamp=((int(time.time()) - 1) // (5 * 60)) * (5 * 60) - (5 * 60)
):
    return f'{symbol}-updown-{interval}-{timestamp}'


def get_market_info_by_slug(slug):
    logger.debug(f"请求市场信息 | slug={slug}")
    url = f"https://gamma-api.polymarket.com/markets/slug/{slug}"
    response = requests.get(url)
    return response.json()


def get_current_position(condition_id=None):
    url = "https://data-api.polymarket.com/positions"
    params = {"user": PROXY_WALLET_ADDRESS}
    if condition_id:
        params['market'] = condition_id

    logger.debug(f"查询当前仓位 | condition_id={condition_id}")
    response = requests.request(url=url, params=params, method="GET")
    return response.json()


def position_manager():
    aligned_timestamp = None
    market_info = {}
    condition_id = market_info.get('conditionId', None)

    event_change = (
        ((int(time.time()) - 1) // (5 * 60)) * (5 * 60) - (5 * 60)
        != aligned_timestamp
    )

    if event_change or not aligned_timestamp:
        aligned_timestamp = (int(time.time() - 1) // (5 * 60)) * (5 * 60) - (5 * 60)
        logger.info(f"检测到新市场周期 | timestamp={aligned_timestamp}")

        slug = generate_current_slug()
        market_info = get_market_info_by_slug(slug)
        condition_id = market_info['conditionId']

        logger.info(f"当前市场 | slug={slug} | condition_id={condition_id}")
        split_position(condition_id)

    current_position = get_current_position()
    up_down_amount_dict = {'Up': 0, 'Down': 0}

    for position in current_position:
        # 非当前时间仓位 → redeem
        if position['conditionId'] != condition_id and position['redeemable']:
            amounts = [0.0, 0.0]
            amounts[position['outcomeIndex']] = position['size']

            logger.info(
                f"Redeem 旧仓位 | condition_id={position['conditionId']} "
                f"| outcome={position['outcome']} | size={position['size']}"
            )

            try:
                POSITION_CLIENT.redeem_position(
                    condition_id=position['conditionId'],
                    amounts=amounts,
                    neg_risk=NEG_RISK
                )
            except Exception as e:
                logger.error(
                    f"Redeem 失败 | condition_id={position['conditionId']} | error={e}",
                    exc_info=True
                )

        # 当前仓位 → 统计
        elif position['conditionId'] == condition_id and not position['redeemable']:
            up_down_amount_dict[position['outcome']] += position['size']

    position_sold = FULL_POS_AMOUNT - max(up_down_amount_dict.values())

    if position_sold / FULL_POS_AMOUNT > ADD_NEW_POSITION_THRESHOLD:
        logger.warning(
            f"仓位不足 | sold={position_sold} | threshold={ADD_NEW_POSITION_THRESHOLD}"
        )
        split_position(condition_id, split_amount=position_sold)
    else:
        logger.info(f"仓位充足 | 当前仓位={up_down_amount_dict}")

    # 卖出权限判断
    selling_permission_dict = {
        'Up': True,
        'Down': True,
        'timestamp': int(time.time())
    }

    if up_down_amount_dict['Up'] - up_down_amount_dict['Down'] > STOP_SELLING_THRESHOLD * FULL_POS_AMOUNT:
        selling_permission_dict['Down'] = False
        logger.warning("仓位失衡 → 停止 Down 方向卖出")

    elif up_down_amount_dict['Down'] - up_down_amount_dict['Up'] > STOP_SELLING_THRESHOLD * FULL_POS_AMOUNT:
        selling_permission_dict['Up'] = False
        logger.warning("仓位失衡 → 停止 Up 方向卖出")

    logger.info(f"卖出权限状态 | {selling_permission_dict}")

    with open('selling_permission_dict.json', 'w') as f:
        json.dump(selling_permission_dict, f)

    return selling_permission_dict


if __name__ == '__main__':
    logger.info("====== Polymarket 仓位管理模块启动 ======")
    position_manager()

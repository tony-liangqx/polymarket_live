from polymarket_apis import PolymarketWeb3Client, PolymarketGammaClient
from eth_typing import HexStr
from polymarket_apis.types import Keccak256


# 1. 配置参数
PRIVATE_KEY = "0x"
SPLIT_AMOUNT_USDC = 10.0  # 要拆分的 USDC 数量
NEG_RISK = False  # 根据市场类型设置
RPC_URL = "https://polygon.drpc.org"

# 初始化 Web3 客户端
client = PolymarketWeb3Client(
    private_key=HexStr(PRIVATE_KEY),
    rpc_url=RPC_URL,
    signature_type=1  # 1=Email/Magic, 2=Safe/Gnosis, 0=EOA
)

balance = client.get_usdc_balance()
print(f"Wallet address: {client.address}, balance: {balance}")

# 执行 split 操作
gammaClient = PolymarketGammaClient()
market = gammaClient.get_market_by_slug("btc-updown-5m-1776576600")
condition_id = market.condition_id
# 必须加判断：不能为空
if not condition_id:
    raise ValueError("condition_id 为空，无法 split")
print(f"condition_id: {condition_id}")
receipt = client.split_position(
           condition_id=condition_id,
           amount=1.0,
       )
print(f"receipt: {receipt}")

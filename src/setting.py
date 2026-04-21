import json
from polymarket_apis import PolymarketGammaClient
from polymarket_apis.clients.web3_client import PolymarketGaslessWeb3Client
from py_clob_client.client import ClobClient

# =========================
# 1. 配置参数
# =========================
#
ORDER_SIZE:int = 10
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

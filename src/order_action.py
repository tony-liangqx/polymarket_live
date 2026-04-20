# 假设你已经初始化了客户端 client
from py_clob_client.clob_types import OrderArgs, OrderType
import setting

#
# @price: 你愿意支付的价格
# @size: 买入数量
#
def Buy(token_id: str, price: float, size: float):
    buy_order_args = OrderArgs(
        price=price, # 你愿意支付的价格
        size=size,  # 买入数量
        side="BUY",
        token_id=token_id
    )
    signed_order = setting.TRADE_CLIENT.create_order(buy_order_args)
    resp = setting.TRADE_CLIENT.post_order(signed_order, orderType=OrderType.GTC) # type: ignore
    return resp


def Cancel():
    return setting.TRADE_CLIENT.cancel_all()


if __name__ == "__main__":
    Cancel()

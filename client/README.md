# QMT 本地执行客户端（Windows）

## 安装
```bash
pip install -r requirements.txt
```

## 运行模式
- `EXECUTION_MODE=AUTO`（默认）：优先连接 xtquant，失败回退 mock
- `EXECUTION_MODE=XT_ONLY`：必须使用 xtquant，连接失败直接退出
- `EXECUTION_MODE=MOCK_ONLY`：仅 mock（联调/演示）

## 配置
环境变量：
- `SERVER_BASE_URL`，默认 `http://localhost:8000/api/v1`
- `CLIENT_ID`，默认 `client_win_001`
- `ACCOUNT_ID`，默认 `acc_stock_main`
- `CLIENT_SHARED_TOKEN`，需与服务端一致
- `SECRET_FILE`，默认 `secrets.enc.json`
- `EXECUTION_MODE`，默认 `AUTO`
- `QMT_ACCOUNT_TYPE`，默认 `STOCK`
- `QMT_STRATEGY_NAME`，默认 `qmt_gateway`
- `QMT_ORDER_REMARK_PREFIX`，默认 `qmtgw`
- `QMT_SESSION_ID`，默认 `10001`

## secrets 文件
推荐在 Windows 生成 DPAPI 加密文件：
```python
from pathlib import Path
from qmt_gateway.secret_store import save_secret_file

save_secret_file(
    Path('secrets.enc.json'),
    {
        'qmt_path': r'D:\\国金证券QMT交易端\\userdata_mini',
        'qmt_account_id': '12345678',
        'account_type': 'STOCK',
        'session_id': 10001,
        'strategy_name': 'qmt_gateway',
        'order_remark_prefix': 'qmtgw'
    }
)
```

字段说明：
- `qmt_path`: miniQMT 用户目录（`userdata_mini`）
- `qmt_account_id`: 资金账号
- `account_type`: `STOCK`（普通股票）
- `session_id`: xttrader 会话ID，建议每个客户端唯一

## 运行
```bash
python -m qmt_gateway.main
```

## 目标仓位信号说明
当 `signal_type=TARGET_POSITION` 时，客户端会：
1. 用 `target_position_ratio` 读取目标仓位占比
2. 从 `extra.reference_price` 获取参考价格
3. 查询 QMT 账户总资产与当前持仓，计算买卖差量

若差量为 0 或不足一手（买入场景），会回报 `CANCELED`（表示无需执行）。

## 常见问题
1. 提示 `xtquant 导入失败`：请确认在 Windows + miniQMT 环境，并安装 `xtquant`。
2. 提示 `connect/subscribe 失败`：检查 `qmt_path`、账号类型、交易端登录状态。
3. 撤单失败：检查 `broker_order_id` 是否为有效 QMT 订单号。

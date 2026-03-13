from qmt_gateway.executor import QmtExecutor
from qmt_gateway.trade_reporting import report_trade_callbacks


class _FakeSettings:
    execution_mode = 'MOCK_ONLY'


class _FakeApi:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def report_trade(self, payload: dict) -> None:
        self.payloads.append(payload)


class _FakeExecutor:
    def __init__(self, trades: list[dict]) -> None:
        self._trades = trades
        self.acked = 0

    def peek_trade_reports(self) -> list[dict]:
        return list(self._trades)

    def ack_trade_reports(self, count: int) -> None:
        self.acked = count


def test_executor_enriches_trade_reports_with_order_id():
    executor = QmtExecutor(secret_payload={}, settings=_FakeSettings())
    executor._broker_order_to_order_id['1099189171'] = 'ord_123'
    executor._xt_enabled = True

    class _Adapter:
        @staticmethod
        def peek_trades() -> list[dict]:
            return [
                {
                    'broker_order_id': '1099189171',
                    'broker_trade_id': 'trd_1',
                    'quantity': 100,
                    'price': 14.06,
                }
            ]

    executor._xt_adapter = _Adapter()

    reports = executor.peek_trade_reports()

    assert reports[0]['order_id'] == 'ord_123'


def test_report_trade_callbacks_prefers_order_id_when_available():
    api = _FakeApi()
    executor = _FakeExecutor(
        [
            {
                'order_id': 'ord_123',
                'broker_order_id': '1099189171',
                'broker_trade_id': 'trd_1',
                'quantity': 100,
                'price': 14.06,
            }
        ]
    )
    last_error = {'msg': None}

    report_trade_callbacks(api=api, executor=executor, client_id='client_win_001', last_error=last_error)

    assert executor.acked == 1
    assert api.payloads == [
        {
            'client_id': 'client_win_001',
            'order_id': 'ord_123',
            'broker_order_id': '1099189171',
            'broker_trade_id': 'trd_1',
            'quantity': 100,
            'price': 14.06,
        }
    ]

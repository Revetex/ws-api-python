from typing import Any, Dict

from external_apis import APIManager, YahooFinanceClient, TelegramNotifier, NewsAPIClient, AlphaVantageClient


def _dummy_yahoo_quote_json(price=123.45, change=1.23, change_pct=1.0) -> Dict[str, Any]:
    return {
        'quoteResponse': {
            'result': [
                {
                    'regularMarketPrice': price,
                    'regularMarketChange': change,
                    'regularMarketChangePercent': change_pct,
                }
            ]
        }
    }


def test_provider_selection_from_env(monkeypatch):
    monkeypatch.setenv('MARKET_DATA_PROVIDER', 'yahoo')
    api = APIManager()
    assert api.market is api.yahoo


def test_api_manager_quote_fallback_to_yahoo(monkeypatch):
    monkeypatch.setenv('MARKET_DATA_PROVIDER', 'alpha')
    api = APIManager()

    # Alpha returns invalid -> triggers Yahoo fallback
    monkeypatch.setattr(api.alpha_vantage, 'get_quote', lambda s: {})

    # Yahoo returns a valid structure
    def fake_get_quote(symbol):  # noqa: ARG001
        return {'05. price': '123', '09. change': '1', '10. change percent': '1%'}

    monkeypatch.setattr(api.yahoo, 'get_quote', fake_get_quote)

    out = api.get_quote('TEST')
    assert out.get('05. price') == '123'


def test_api_manager_series_fallback_intraday_then_daily(monkeypatch):
    monkeypatch.setenv('MARKET_DATA_PROVIDER', 'alpha')
    api = APIManager()

    monkeypatch.setattr(api.alpha_vantage, 'get_time_series', lambda *a, **k: {})

    def fake_yahoo_series(symbol, interval='1day', outputsize='compact'):  # noqa: ARG001
        if interval != '1day':
            return {}
        return {'Time Series (Daily)': {'2025-01-01': {'4. close': '1.0'}}}

    monkeypatch.setattr(api.yahoo, 'get_time_series', fake_yahoo_series)

    out = api.get_time_series('TEST', interval='5min', outputsize='compact')
    # Should fallback to daily structure
    assert any('time series' in k.lower() and v for k, v in out.items())


def test_telegram_send_message_without_config():
    tn = TelegramNotifier(bot_token=None, chat_id=None)
    assert tn.send_message('hello') is False


def test_telegram_send_message_to_with_token(monkeypatch):
    calls = {'count': 0, 'data': None}

    class DummyResp:
        status_code = 200

        def raise_for_status(self):
            return None

    def fake_post(url, json=None, timeout=10):  # noqa: ARG001
        calls['count'] += 1
        calls['data'] = json
        return DummyResp()

    monkeypatch.setattr('external_apis.requests.post', fake_post)

    tn = TelegramNotifier(bot_token='x', chat_id=None)
    ok = tn.send_message_to('123', 'Hi')
    assert ok is True
    assert calls['count'] == 1
    assert calls['data'] and calls['data']['chat_id'] == '123'


def test_yahoo_quote_caches_within_ttl(monkeypatch):
    yf = YahooFinanceClient()
    # Control time
    t0 = 1000.0
    monkeypatch.setattr('external_apis.time.time', lambda: t0)

    calls = {'count': 0}

    class DummyResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return _dummy_yahoo_quote_json()

    def fake_get(url, params=None, timeout=10):  # noqa: ARG001
        calls['count'] += 1
        return DummyResp()

    # Patch the session on this instance only
    yf._session.get = fake_get  # type: ignore[attr-defined]

    out1 = yf.get_quote('AAA')
    assert out1.get('05. price') == '123.45'
    assert calls['count'] == 1

    # Within TTL (60s) -> should use cache, no extra call
    monkeypatch.setattr('external_apis.time.time', lambda: t0 + 10)
    out2 = yf.get_quote('AAA')
    assert out2 == out1
    assert calls['count'] == 1


def test_yahoo_quote_respects_rate_limit_with_cache(monkeypatch):
    yf = YahooFinanceClient()
    # Seed cache
    yf._quote_cache['AAA'] = (1000.0, {'05. price': '111'})
    # Force rate-limited window
    yf._next_allowed_ts = 2000.0
    # Current time within the rate-limited window
    monkeypatch.setattr('external_apis.time.time', lambda: 1500.0)

    calls = {'count': 0}

    def fake_get(url, params=None, timeout=10):  # noqa: ARG001
        calls['count'] += 1
        raise AssertionError('network should not be called when rate-limited and cache exists')

    yf._session.get = fake_get  # type: ignore[attr-defined]

    out = yf.get_quote('AAA')
    assert out.get('05. price') == '111'
    assert calls['count'] == 0


def test_api_manager_notify_alert_levels(monkeypatch):
    api = APIManager()
    seen = {'args': None}

    def fake_send_alert(title, message, level):  # noqa: ARG001
        seen['args'] = (title, message, level)
        return True

    monkeypatch.setattr(api.telegram, 'send_alert', fake_send_alert)

    # INFO should not call telegram
    ok_info = api.notify_alert('INFO', 'X', 'msg')
    assert ok_info is True
    assert seen['args'] is None

    # ALERT should call telegram
    ok_alert = api.notify_alert('ALERT', 'X', 'msg')
    assert ok_alert is True
    assert seen['args'] is not None


def test_api_manager_notify_info_technical(monkeypatch):
    api = APIManager()
    seen = {'args': None}

    def fake_send_alert(title, message, level):  # noqa: ARG001
        seen['args'] = (title, message, level)
        return True

    monkeypatch.setattr(api.telegram, 'send_alert', fake_send_alert)

    # Non-technical INFO should NOT call telegram
    seen['args'] = None
    ok = api.notify_alert('INFO', 'INFO_NOTE', 'hello')
    assert ok is True and seen['args'] is None

    # Technical INFO should call telegram
    seen['args'] = None
    ok = api.notify_alert('INFO', 'TECH_BUY', 'SMA signal BUY AAA')
    assert ok is True and seen['args'] is not None


def test_clients_without_keys_return_empty(monkeypatch):
    # Ensure env keys are not set
    for key in ('NEWS_API_KEY', 'ALPHA_VANTAGE_KEY'):
        monkeypatch.delenv(key, raising=False)

    news = NewsAPIClient(api_key=None)
    av = AlphaVantageClient(api_key=None)

    assert news.get_financial_news('x') == []
    assert news.get_company_news('AAPL') == []
    assert av.get_quote('AAPL') is None
    assert av.get_time_series('AAPL') is None

import pytest

from ai_agent import AIAgent
from external_apis import APIManager


class FakeTelegram:
    def __init__(self):
        self.calls = []

    def send_alert(self, title: str, message: str, level: str = "INFO") -> bool:
        self.calls.append({"title": title, "message": message, "level": level})
        return True


class FakeAppConfig:
    def __init__(self, enabled: bool, include_tech: bool):
        self.enabled = enabled
        self.include_tech = include_tech
        self.notifications = {
            'info': False,
            'warn': True,
            'alert': True,
        }

    def get(self, key: str, default=None):
        if key == 'integrations.telegram.enabled':
            return self.enabled
        if key == 'integrations.telegram.include_technical':
            return self.include_tech
        if key == 'notifications.info':
            return self.notifications['info']
        if key == 'notifications.warn':
            return self.notifications['warn']
        if key == 'notifications.alert':
            return self.notifications['alert']
        return default

    def set(self, key: str, value):
        if key == 'integrations.telegram.enabled':
            self.enabled = bool(value)
        elif key == 'integrations.telegram.include_technical':
            self.include_tech = bool(value)
        elif key.startswith('notifications.'):
            sub = key.split('.', 1)[1]
            if sub in self.notifications:
                self.notifications[sub] = bool(value)


@pytest.fixture()
def patch_app_config(monkeypatch):
    import wsapp_gui.config as cfg

    def _apply(enabled: bool, include_tech: bool):
        monkeypatch.setattr(cfg, 'app_config', FakeAppConfig(enabled, include_tech), raising=True)

    return _apply


def test_notify_alert_disabled_skips_sending(monkeypatch, patch_app_config):
    patch_app_config(enabled=False, include_tech=True)
    api = APIManager()
    fake = FakeTelegram()
    monkeypatch.setattr(api, 'telegram', fake, raising=True)

    # WARN should normally send; but disabled means skip
    ok = api.notify_alert('WARN', 'PNL_DROP', 'drop msg')
    assert ok is True
    assert fake.calls == []


def test_notify_alert_tech_info_respects_include_technical(monkeypatch, patch_app_config):
    # Enabled + include technical => should send
    patch_app_config(enabled=True, include_tech=True)
    api = APIManager()
    fake = FakeTelegram()
    monkeypatch.setattr(api, 'telegram', fake, raising=True)
    ok = api.notify_alert('INFO', 'TECH_BUY_AAPL', 'SMA BUY')
    assert ok is True
    assert len(fake.calls) == 1
    assert 'TECH_BUY_AAPL' in fake.calls[0]['title']

    # Enabled but exclude technical => should not send
    patch_app_config(enabled=True, include_tech=False)
    api2 = APIManager()
    fake2 = FakeTelegram()
    monkeypatch.setattr(api2, 'telegram', fake2, raising=True)
    ok2 = api2.notify_alert('INFO', 'TECH_SELL_MSFT', 'SMA SELL')
    assert ok2 is True
    assert fake2.calls == []


def test_notify_alert_warn_sends_when_enabled(monkeypatch, patch_app_config):
    patch_app_config(enabled=True, include_tech=False)
    api = APIManager()
    fake = FakeTelegram()
    monkeypatch.setattr(api, 'telegram', fake, raising=True)
    ok = api.notify_alert('WARN', 'PNL_DOWN', 'warn msg')
    assert ok is True
    assert len(fake.calls) == 1
    assert fake.calls[0]['level'] == 'WARN'


def test_notify_alert_level_gating_warn_and_alert(monkeypatch, patch_app_config):
    # Disable WARN -> should skip warn sends
    patch_app_config(enabled=True, include_tech=True)
    from wsapp_gui.config import app_config

    app_config.set('notifications.warn', False)
    api = APIManager()
    fake = FakeTelegram()
    monkeypatch.setattr(api, 'telegram', fake, raising=True)
    ok = api.notify_alert('WARN', 'PNL_DOWN', 'warn msg')
    assert ok is True
    assert fake.calls == []

    # ALERT still allowed by default
    patch_app_config(enabled=True, include_tech=True)
    api2 = APIManager()
    fake2 = FakeTelegram()
    monkeypatch.setattr(api2, 'telegram', fake2, raising=True)
    ok2 = api2.notify_alert('ALERT', 'PNL_DROP', 'drop msg')
    assert ok2 is True
    assert len(fake2.calls) == 1
    assert fake2.calls[0]['level'] == 'ALERT'


def test_ai_agent_symbol_detection_word_boundaries():
    agent = AIAgent(enable_gemini=False, enable_notifications=False)
    # Portfolio with potentially ambiguous symbol
    agent.last_positions = [
        # ... minimal positions for test
        type(
            'P',
            (),
            {
                'symbol': 'ALL',
                'name': 'Allstate',
                'quantity': 1.0,
                'value': 100.0,
                'currency': 'USD',
                'pnl_abs': None,
                'pnl_pct': None,
            },
        )(),
        type(
            'P',
            (),
            {
                'symbol': 'AAPL',
                'name': 'Apple',
                'quantity': 1.0,
                'value': 200.0,
                'currency': 'USD',
                'pnl_abs': None,
                'pnl_pct': None,
            },
        )(),
    ]
    # The word 'allocation' contains 'ALL' but should not match as a symbol
    found = agent._find_symbols_in_text('Vérifions la diversification et l\'allocation actuelle')
    assert 'ALL' not in found
    # Should match AAPL exactly
    found2 = agent._find_symbols_in_text('Que penses-tu de AAPL aujourd\'hui ?')
    assert 'AAPL' in found2


def test_ai_agent_reads_include_technical_from_app_config(patch_app_config):
    # include_technical=False should disable technical alerts emission
    patch_app_config(enabled=True, include_tech=False)
    agent = AIAgent(enable_gemini=False, enable_notifications=False)
    assert agent.allow_technical_alerts is False

    # include_technical=True should enable
    patch_app_config(enabled=True, include_tech=True)
    agent2 = AIAgent(enable_gemini=False, enable_notifications=False)
    assert agent2.allow_technical_alerts is True

from ai_agent import AIAgent


class DummyAPIManager:
    def __init__(self):
        self.sent = []

    def notify_alert(self, level, code, message):
        self.sent.append((level, code, message))


def test_generate_signals_and_gating(monkeypatch):
    agent = AIAgent(enable_gemini=False, enable_notifications=True)

    # Inject dummy API manager and gating predicate
    dam = DummyAPIManager()
    agent.api_manager = dam
    agent.enable_notifications = True

    # Gate disabled: notifications should not be sent
    agent.notifications_allowed = lambda: False

    positions = [
        {"symbol": "AAA", "name": "A", "quantity": 10, "value": 1000, "pnlPct": -20.0},
        {"symbol": "BBB", "name": "B", "quantity": 10, "value": 50, "pnlPct": 1.0},
        {"symbol": "CAD", "name": "Cash", "quantity": 1, "value": 1, "pnlPct": None},
    ]

    agent.on_positions(positions)
    sigs = agent.get_signals()
    assert sigs, "Should produce signals"

    # No notifications due to gating
    assert dam.sent == []

    # Enable gate and emit another signal
    agent.notifications_allowed = lambda: True
    # Trigger a cash ratio signal by near zero cash
    agent.on_positions([
        {"symbol": "AAA", "name": "A", "quantity": 10, "value": 1000, "pnlPct": 0.0},
    ])
    assert dam.sent, "Expected notifications when gate is enabled"


def test_technical_alerts_toggle_routes_info(monkeypatch):
    # Arrange agent and dummy API manager to capture sends
    agent = AIAgent(enable_gemini=False, enable_notifications=True)

    class DummyAM:
        def __init__(self):
            self.sent = []

        def notify_alert(self, level, code, message):
            self.sent.append((level, code, message))
            return True

    dam = DummyAM()
    agent.api_manager = dam
    agent.notifications_allowed = lambda: True

    # Simulate direct TECH_* emission through internal emitter
    agent.allow_technical_alerts = False
    agent._emit('INFO', 'TECH_BUY', 'SMA BUY AAA')  # gated off
    assert dam.sent == []

    agent.allow_technical_alerts = True
    agent._emit('INFO', 'TECH_BUY', 'SMA BUY AAA')  # allowed and should route via APIManager
    assert any(code == 'TECH_BUY' and level == 'INFO' for (level, code, msg) in dam.sent)

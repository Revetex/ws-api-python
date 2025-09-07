import pytest

from wsapp_gui.charts import HAS_MPL, ChartController


class DummyApp:
    def __init__(self):
        self.api = None
        self.current_account_id = None

    def _busy(self, *_a, **_k):
        pass

    def after(self, _ms, cb):
        if callable(cb):
            cb()

    def set_status(self, *_a, **_k):
        pass


@pytest.mark.skipif(not HAS_MPL, reason="Matplotlib not available")
def test_markers_set_and_replot(monkeypatch):
    app = DummyApp()
    cc = ChartController(app)

    # Seed cached line
    points = [("2024-01-01", 100.0), ("2024-01-02", 105.0), ("2024-01-03", 103.0)]
    cc._last_points = points
    cc._last_title = "Test"

    called = {"count": 0}

    def fake_update_line(p, t):
        called["count"] += 1
        assert p == points and t == "Test"

    monkeypatch.setattr(cc, "_update_line", fake_update_line)

    # Set markers should trigger a replot
    markers = [
        {"date": "2024-01-02", "kind": "buy", "y": 104.0, "label": "BUY"},
        {"date": "2024-01-03", "kind": "sell", "label": "SELL"},
    ]
    cc.set_markers(markers)

    assert called["count"] == 1

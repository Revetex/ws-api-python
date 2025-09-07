import tkinter as tk

import pytest

from wsapp_gui.charts import HAS_MPL, ChartController


class DummyAPI:
    def get_account_historical_financials(self, *args, **kwargs):
        # return a few daily points mimicking GraphQL edges
        return [
            {"node": {"date": "2024-01-01", "netLiquidationValueV2": {"amount": 100.0}}},
            {"node": {"date": "2024-01-02", "netLiquidationValueV2": {"amount": 110.0}}},
        ]


class DummyApp:
    def __init__(self):
        self.api = DummyAPI()
        self.current_account_id = "acc1"

    def _busy(self, *_a, **_k):
        pass

    def after(self, _ms, cb):
        # call immediately for test simplicity
        if callable(cb):
            cb()

    def set_status(self, *_a, **_k):
        pass


@pytest.mark.skipif(not HAS_MPL, reason="Matplotlib not available")
def test_chartcontroller_line_chart(monkeypatch):
    app = DummyApp()
    cc = ChartController(app)
    # Use a real Tk parent so TkAgg can attach a Canvas
    root = tk.Tk()
    root.withdraw()
    parent = tk.Frame(root)
    parent.pack()
    try:
        cc.init_widgets(parent)
        assert cc.canvas is not None
        # Should not raise and should call update
        cc.load_nlv_single()
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_chartcontroller_export_csv(tmp_path):
    app = DummyApp()
    cc = ChartController(app)
    # Seed cached points for export
    cc._last_points = [
        ("2024-01-01", 100.0),
        ("2024-01-02", 110.5),
    ]
    out = tmp_path / "nlv.csv"
    ok = cc.export_csv(str(out))
    assert ok is True
    content = out.read_text(encoding="utf-8").strip().splitlines()
    # header + 2 rows
    assert content[0] == "date,value"
    assert content[1].startswith("2024-01-01,")
    assert content[2].startswith("2024-01-02,")


def test_chartcontroller_set_options_triggers_replot(monkeypatch):
    app = DummyApp()
    cc = ChartController(app)
    # Prepare cached data to allow replot path
    points = [("2024-01-01", 1.0)]
    title = "Test"
    cc._last_points = points
    cc._last_title = title

    called = {"count": 0, "args": None}

    def fake_update_line(p, t):
        called["count"] += 1
        called["args"] = (p, t)

    monkeypatch.setattr(cc, "_update_line", fake_update_line)

    # Toggle options and verify they are applied and replot was invoked
    cc.set_options(show_grid=False, show_sma=True, sma_window=5)
    assert cc._show_grid is False
    assert cc._show_sma is True
    assert cc._sma_window == 5
    assert called["count"] == 1
    assert called["args"] == (points, title)


@pytest.mark.skipif(not HAS_MPL, reason="Matplotlib not available")
def test_chartcontroller_export_png_smoke(tmp_path):
    # Build a minimal Figure without needing Tk
    from matplotlib.figure import Figure  # type: ignore

    app = DummyApp()
    cc = ChartController(app)
    fig = Figure(figsize=(2, 2))
    ax = fig.add_subplot(111)
    ax.plot([0, 1, 2], [1, 2, 3])
    cc.figure = fig

    out = tmp_path / "plot.png"
    ok = cc.export_png(str(out))
    assert ok is True
    assert out.exists() and out.stat().st_size > 0

from enhanced_ai_system import (
    AnalyticsEngine,
    Communicator,
    Decision,
    DecisionEngine,
    EnhancedAI,
    Safety,
)


def test_safety_mask_text_email_and_digits():
    s = Safety()
    inp = "Contact: john.doe@example.com, tel: 1234567890123"
    out = s.mask_text(inp)
    assert "[email masqué]" in out
    assert "[numéro masqué]23" in out  # keeps last 2 digits


def test_safety_moderation_blocks_strong_profanity():
    s = Safety()
    assert s.moderate_text("hello") is True
    assert s.moderate_text("this is fuck word") is False


def test_decision_engine_buy_with_cash_and_sma_cross():
    # Positions: AAA (equity), BBB (small), CAD (cash)
    positions = [
        {"symbol": "AAA", "value": 900.0, "sma5": 11.0, "sma20": 10.0, "rsi": 50.0},
        {"symbol": "BBB", "value": 100.0},
        {"symbol": "CAD", "value": 500.0},
    ]
    de = DecisionEngine(max_symbol_share_pct=100.0, max_sector_share_pct=100.0)
    d = de.suggest(positions, symbol="AAA")
    # Cash ratio >= 30 and SMA5 > SMA20 should bias to BUY or at least not SELL
    assert d.symbol == "AAA"
    assert d.action in ("BUY", "HOLD")
    # Rationale should mention SMA bias
    assert ("SMA5 > SMA20" in d.rationale) or ("Cash disponible" in d.rationale)


def test_decision_engine_symbol_budget_triggers_sell_from_buy():
    # Set high cash to trigger initial BUY, then exceed symbol budget to force SELL
    positions = [
        {"symbol": "AAA", "value": 900.0},
        {"symbol": "BBB", "value": 100.0},
        {"symbol": "CAD", "value": 600.0},  # cash_ratio = 600/1600 = 37.5% -> BUY bias
    ]
    de = DecisionEngine(max_symbol_share_pct=20.0)
    d = de.suggest(positions, symbol="AAA")
    # Because initial action would be BUY (cash), symbol overweight flips to SELL
    assert d.action == "SELL"
    assert any("Poids" in n for n in d.safety_notes)


def test_decision_engine_sector_limit_holds_buy():
    # Two tech names overweight a sector; cash triggers BUY, sector rule downgrades to HOLD
    positions = [
        {"symbol": "AAA", "value": 400.0, "sector": "Tech"},
        {"symbol": "BBB", "value": 300.0, "sector": "Tech"},
        {"symbol": "CAD", "value": 450.0},  # cash ~39%, BUY bias
    ]
    # Allow high per-symbol budget to ensure sector rule is the limiter
    de = DecisionEngine(max_sector_share_pct=40.0, max_symbol_share_pct=80.0)
    d = de.suggest(positions, symbol="AAA")
    assert d.action == "HOLD"
    assert any("Secteur" in n for n in d.safety_notes)


def test_communicator_masks_without_blocking():
    s = Safety()
    c = Communicator(safety=s)
    d = Decision(
        action="BUY",
        symbol="AAA",
        confidence=0.7,
        rationale="Ecrivez-moi: a@b.com, tel 2223334444555",
    )
    txt = c.format_decision(d)
    assert "[email masqué]" in txt
    assert "[numéro masqué]55" in txt
    assert txt != "[Contenu modéré]"


def test_enhanced_ai_end_to_end():
    ai = EnhancedAI(deterministic=True)
    positions = [
        {"symbol": "AAA", "value": 500.0, "sma5": 10.0, "sma20": 9.0, "rsi": 55.0},
        {"symbol": "BBB", "value": 300.0},
        {"symbol": "CAD", "value": 400.0},
    ]
    res = ai.analyze_and_suggest(positions, focus_symbol="AAA")
    assert set(res.keys()) == {"analytics", "decision"}
    assert isinstance(res["analytics"], str) and len(res["analytics"]) > 0
    assert isinstance(res["decision"], str) and len(res["decision"]) > 0


def sample_positions():
    return [
        {"symbol": "AAPL", "value": 10000.0, "pnlAbs": 500.0, "pnlPct": 5.0},
        {"symbol": "MSFT", "value": 8000.0, "pnlAbs": -200.0, "pnlPct": -2.5},
        {"symbol": "CAD", "value": 7000.0},
    ]


def test_analytics_basic():
    ae = AnalyticsEngine()
    m = ae.compute_metrics(sample_positions())
    assert m["total_value"] == 25000.0
    assert m["n_positions"] == 2  # CAD treated as cash
    assert 0.0 <= m["hhi_normalized"] <= 1.0
    assert 0.0 <= m["cash_ratio"] <= 100.0


def test_decision_and_formatting():
    safety = Safety(max_per_minute=1000, deterministic=True)
    de = DecisionEngine(safety=safety)
    pos = sample_positions()
    m = AnalyticsEngine().compute_metrics(pos)
    d = de.suggest(pos, metrics=m)
    assert d.action in {"BUY", "SELL", "HOLD", "INFO", "REBALANCE"}
    cm = Communicator(safety=safety)
    txt = cm.format_decision(d, context="ctx")
    assert isinstance(txt, str) and len(txt) > 0


def test_enhanced_ai_facade():
    ai = EnhancedAI(deterministic=True)
    ai.memory.add("user", "Salut, montre moi le résumé.")
    out = ai.analyze_and_suggest(sample_positions(), lang="fr")
    assert "analytics" in out and "decision" in out
    assert isinstance(out["analytics"], str)
    assert isinstance(out["decision"], str)


def test_safety_moderation_and_rate_limit():
    s = Safety(max_per_minute=2)
    assert s.moderate_text("Bonjour") is True
    assert s.moderate_text("fuck that") is False
    assert s.rate_limit("k") is True
    assert s.rate_limit("k") is True
    # Third within the minute should fail
    assert s.rate_limit("k") is False


def test_context_memory_summarize_edges():
    from enhanced_ai_system import ContextMemory

    mem = ContextMemory(max_items=6)
    # Empty
    assert mem.summarize().strip() == ""
    # Add more than max; ensure truncation and prefix
    for i in range(10):
        mem.add('user' if i % 2 == 0 else 'assistant', f"msg{i}")
    out = mem.summarize()
    # Older prefix may appear depending on current rolling size; allow either
    assert ("…" in out) or ("msg4" in out) or ("msg6" in out)
    # Should include tail messages with role markers (implementation keeps recent half on overflow)
    for i in range(6, 10):
        assert f"msg{i}" in out
    assert ("[U]" in out) or ("[A]" in out)

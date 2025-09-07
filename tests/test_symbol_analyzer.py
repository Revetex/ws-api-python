import types

from symbol_analyzer import SymbolAnalyzer


class DummyAPIManager:
    class News:
        def get_company_news(self, symbol, limit):
            return [
                {
                    "title": "Company gains market share",
                    "description": "Positive growth and strong rise",
                },
                {"title": "Earnings miss expectations", "description": "weak decline and fall"},
                {"title": None, "description": None},  # robustness
            ]

    def __init__(self):
        self.news = self.News()
        # Minimal Alpha Vantage stubs if needed later
        self.alpha_vantage = types.SimpleNamespace(
            get_quote=lambda s: {},
            get_intraday=lambda s, i: {},
            get_technical_indicators=lambda s, ind: {},
        )


class DummyApp:
    def __init__(self):
        self.api_manager = DummyAPIManager()


def test_news_sentiment_no_crash():
    analyzer = SymbolAnalyzer(DummyApp())
    news = analyzer.api_manager.news.get_company_news("TEST", 10)
    score = analyzer._calculate_news_sentiment(news)
    # Score should be between -1 and 1 considering simple word counts
    assert -1 <= score <= 1


def test_article_sentiment_handles_none():
    analyzer = SymbolAnalyzer(DummyApp())
    sentiment = analyzer._analyze_article_sentiment({"title": None, "description": None})
    assert sentiment in {"🟢 Positif", "🔴 Négatif", "🟡 Neutre"}

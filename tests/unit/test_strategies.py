"""Unit tests for trading strategies."""

from pathlib import Path

import pytest

from kalshi_trading.clients.espn import GameState, GameStatus, Team
from kalshi_trading.clients.models import Market, MarketStatus, Position
from kalshi_trading.config import (
    ConfigError,
    create_strategy_from_config,
    load_strategy_from_file,
    load_yaml_config,
)
from kalshi_trading.strategies import (
    CompositeStrategy,
    GameTimeStrategy,
    MarketState,
    ScoreMarginStrategy,
    Signal,
    TradeSignal,
    TradingStrategy,
)


# -- Fixtures --


@pytest.fixture
def home_team() -> Team:
    return Team(id="1", abbreviation="BUF", display_name="Buffalo Bills")


@pytest.fixture
def away_team() -> Team:
    return Team(id="2", abbreviation="KC", display_name="Kansas City Chiefs")


@pytest.fixture
def live_game(home_team: Team, away_team: Team) -> GameState:
    """Game in progress with home team leading."""
    return GameState(
        event_id="12345",
        sport="nfl",
        home_team=home_team,
        away_team=away_team,
        home_score=21,
        away_score=14,
        period=4,
        clock_seconds=300.0,  # 5 minutes left
        status=GameStatus.IN,
    )


@pytest.fixture
def open_market() -> MarketState:
    """Open market for testing."""
    market = Market(
        ticker="NFL-2426-BUF",
        event_ticker="NFL-2426",
        title="Will the Buffalo Bills win?",
        status=MarketStatus.OPEN,
        yes_bid=62,
        yes_ask=64,
        no_bid=36,
        no_ask=38,
        volume=15420,
        open_interest=8234,
    )
    return MarketState(market=market)


# -- Signal Tests --


class TestTradingSignal:
    """Tests for TradeSignal model."""

    def test_signal_types(self):
        """Signal enum should have BUY, SELL, HOLD."""
        assert Signal.BUY.value == "buy"
        assert Signal.SELL.value == "sell"
        assert Signal.HOLD.value == "hold"

    def test_trade_signal_creation(self):
        """TradeSignal should be creatable with all fields."""
        signal = TradeSignal(
            signal=Signal.BUY,
            ticker="NFL-2426-BUF",
            side="yes",
            size=10,
            price=64,
            reason="Test signal",
        )

        assert signal.signal == Signal.BUY
        assert signal.ticker == "NFL-2426-BUF"
        assert signal.size == 10
        assert signal.is_actionable is True

    def test_hold_signal_not_actionable(self):
        """HOLD signals should not be actionable."""
        signal = TradeSignal(
            signal=Signal.HOLD,
            ticker="NFL-2426-BUF",
            side="yes",
            size=0,
        )

        assert signal.is_actionable is False


# -- Score Margin Strategy Tests --


class TestScoreMarginStrategy:
    """Tests for score margin strategy."""

    def test_triggers_when_margin_exceeded(
        self, live_game: GameState, open_market: MarketState
    ):
        """Should trigger when margin exceeds threshold."""
        strategy = ScoreMarginStrategy(
            name="test",
            config={"min_margin": 7, "direction": "leading", "size": 10},
        )

        signal = strategy.evaluate(live_game, open_market, None)

        assert signal is not None
        assert signal.signal == Signal.BUY
        assert signal.size == 10

    def test_no_trigger_when_margin_below_threshold(
        self, live_game: GameState, open_market: MarketState
    ):
        """Should not trigger when margin below threshold."""
        strategy = ScoreMarginStrategy(
            name="test",
            config={"min_margin": 10, "direction": "leading"},  # Need 10, have 7
        )

        signal = strategy.evaluate(live_game, open_market, None)

        assert signal is None

    def test_respects_direction_leading(
        self, live_game: GameState, open_market: MarketState
    ):
        """Should only trigger when target team is leading."""
        strategy = ScoreMarginStrategy(
            name="test",
            config={"min_margin": 7, "direction": "leading"},
        )

        signal = strategy.evaluate(live_game, open_market, None)
        assert signal is not None  # Home team is leading

    def test_respects_direction_trailing(
        self, live_game: GameState, open_market: MarketState
    ):
        """Should only trigger when target team is trailing."""
        strategy = ScoreMarginStrategy(
            name="test",
            config={"min_margin": 7, "direction": "trailing"},
        )

        signal = strategy.evaluate(live_game, open_market, None)
        assert signal is None  # Home team is leading, not trailing

    def test_no_trigger_when_game_not_live(
        self, home_team: Team, away_team: Team, open_market: MarketState
    ):
        """Should not trigger for pre/post game."""
        pre_game = GameState(
            event_id="12345",
            sport="nfl",
            home_team=home_team,
            away_team=away_team,
            home_score=0,
            away_score=0,
            period=0,
            clock_seconds=0,
            status=GameStatus.PRE,
        )

        strategy = ScoreMarginStrategy(
            name="test",
            config={"min_margin": 7, "direction": "leading"},
        )

        signal = strategy.evaluate(pre_game, open_market, None)
        assert signal is None

    def test_requires_min_margin_config(self):
        """Should raise error if min_margin not provided."""
        with pytest.raises(ValueError, match="min_margin"):
            ScoreMarginStrategy(name="test", config={})


# -- Game Time Strategy Tests --


class TestGameTimeStrategy:
    """Tests for game time strategy."""

    def test_valid_time_in_target_period(self, live_game: GameState):
        """Should be valid when in correct period."""
        strategy = GameTimeStrategy(
            name="test",
            config={"min_period": 4},
        )

        assert strategy.is_time_valid(live_game) is True

    def test_invalid_time_before_target_period(
        self, home_team: Team, away_team: Team
    ):
        """Should not be valid before target period."""
        early_game = GameState(
            event_id="12345",
            sport="nfl",
            home_team=home_team,
            away_team=away_team,
            home_score=7,
            away_score=0,
            period=1,  # 1st quarter
            clock_seconds=600,
            status=GameStatus.IN,
        )

        strategy = GameTimeStrategy(
            name="test",
            config={"min_period": 4},  # Requires 4th quarter
        )

        assert strategy.is_time_valid(early_game) is False

    def test_respects_clock_threshold(self, home_team: Team, away_team: Team):
        """Should only be valid when clock below threshold."""
        late_game = GameState(
            event_id="12345",
            sport="nfl",
            home_team=home_team,
            away_team=away_team,
            home_score=21,
            away_score=14,
            period=4,
            clock_seconds=120.0,  # 2 minutes left
            status=GameStatus.IN,
        )

        strategy = GameTimeStrategy(
            name="test",
            config={"min_period": 4, "max_clock": 300},  # Under 5 minutes
        )

        assert strategy.is_time_valid(late_game) is True

    def test_requires_min_period_config(self):
        """Should raise error if min_period not provided."""
        with pytest.raises(ValueError, match="min_period"):
            GameTimeStrategy(name="test", config={})


# -- Composite Strategy Tests --


class TestCompositeStrategy:
    """Tests for composite strategy."""

    def test_and_operator_all_conditions_true(
        self, live_game: GameState, open_market: MarketState
    ):
        """Should trigger when all conditions met with AND."""
        margin_strategy = ScoreMarginStrategy(
            name="margin",
            config={"min_margin": 7, "direction": "leading", "size": 10},
        )
        time_strategy = GameTimeStrategy(
            name="time",
            config={"min_period": 4},
        )

        composite = CompositeStrategy(
            name="composite",
            config={"operator": "and"},
            strategies=[time_strategy, margin_strategy],
        )

        signal = composite.evaluate(live_game, open_market, None)
        assert signal is not None
        assert signal.signal == Signal.BUY

    def test_and_operator_one_condition_false(
        self, home_team: Team, away_team: Team, open_market: MarketState
    ):
        """Should not trigger when any condition fails with AND."""
        early_game = GameState(
            event_id="12345",
            sport="nfl",
            home_team=home_team,
            away_team=away_team,
            home_score=21,
            away_score=14,
            period=1,  # 1st quarter - fails time condition
            clock_seconds=600,
            status=GameStatus.IN,
        )

        margin_strategy = ScoreMarginStrategy(
            name="margin",
            config={"min_margin": 7, "direction": "leading"},
        )
        time_strategy = GameTimeStrategy(
            name="time",
            config={"min_period": 4},  # Requires 4th quarter
        )

        composite = CompositeStrategy(
            name="composite",
            config={"operator": "and"},
            strategies=[time_strategy, margin_strategy],
        )

        signal = composite.evaluate(early_game, open_market, None)
        assert signal is None


# -- Config Loading Tests --


class TestStrategyConfiguration:
    """Tests for strategy config loading."""

    def test_load_valid_yaml(self, tmp_path: Path):
        """Should load valid YAML configuration."""
        config_file = tmp_path / "test.yaml"
        config_file.write_text("""
name: test_strategy
enabled: true
entry_conditions:
  - type: score_margin
    params:
      min_margin: 7
      direction: leading
""")

        config = load_yaml_config(config_file)

        assert config["name"] == "test_strategy"
        assert config["enabled"] is True

    def test_create_strategy_from_config(self):
        """Should create strategy from config dict."""
        config = {
            "name": "margin_strategy",
            "type": "score_margin",
            "params": {"min_margin": 7, "direction": "leading"},
        }

        strategy = create_strategy_from_config(config)

        assert isinstance(strategy, ScoreMarginStrategy)
        assert strategy.name == "margin_strategy"

    def test_validate_required_fields(self):
        """Should reject config missing required fields."""
        config = {"name": "bad_config"}  # Missing 'type'

        with pytest.raises(ConfigError, match="type"):
            create_strategy_from_config(config)

    def test_validate_unknown_strategy_type(self):
        """Should reject unknown strategy types."""
        config = {"name": "bad", "type": "unknown_type"}

        with pytest.raises(ConfigError, match="Unknown strategy type"):
            create_strategy_from_config(config)

    def test_load_strategy_from_file(self, tmp_path: Path):
        """Should load strategy from YAML file."""
        config_file = tmp_path / "strategy.yaml"
        config_file.write_text("""
name: nfl_spread
enabled: true
entry_conditions:
  - type: score_margin
    params:
      min_margin: 7
      direction: leading
trade:
  side: yes
  size: 10
""")

        strategy = load_strategy_from_file(config_file)

        assert strategy.name == "nfl_spread"
        assert isinstance(strategy, ScoreMarginStrategy)

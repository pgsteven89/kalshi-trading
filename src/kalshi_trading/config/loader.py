"""Configuration loading and strategy factory."""

from pathlib import Path
from typing import Any

import yaml

from kalshi_trading.strategies.base import TradingStrategy
from kalshi_trading.strategies.scoreboard import (
    CompositeStrategy,
    GameTimeStrategy,
    ScoreMarginStrategy,
)


class ConfigError(Exception):
    """Raised when configuration is invalid."""

    pass


# Registry of available strategy types
STRATEGY_TYPES: dict[str, type[TradingStrategy]] = {
    "score_margin": ScoreMarginStrategy,
    "game_time": GameTimeStrategy,
    "composite": CompositeStrategy,
}


def load_yaml_config(path: Path) -> dict[str, Any]:
    """
    Load YAML configuration file.

    Args:
        path: Path to YAML file

    Returns:
        Parsed configuration dict

    Raises:
        ConfigError: If file doesn't exist or is invalid
    """
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {path}: {e}")

    if not isinstance(config, dict):
        raise ConfigError(f"Config must be a dict, got {type(config)}")

    return config


def create_strategy_from_config(config: dict[str, Any]) -> TradingStrategy:
    """
    Create a strategy instance from configuration.

    Args:
        config: Strategy configuration dict with 'type' and 'params'

    Returns:
        Configured TradingStrategy instance

    Raises:
        ConfigError: If configuration is invalid
    """
    # Get strategy name
    name = config.get("name", "unnamed")

    # Handle entry_conditions format (from YAML strategy files)
    if "entry_conditions" in config:
        return _create_from_entry_conditions(config)

    # Handle direct type specification
    strategy_type = config.get("type")
    if not strategy_type:
        raise ConfigError("Strategy config must have 'type' field")

    if strategy_type not in STRATEGY_TYPES:
        available = ", ".join(STRATEGY_TYPES.keys())
        raise ConfigError(f"Unknown strategy type '{strategy_type}'. Available: {available}")

    strategy_class = STRATEGY_TYPES[strategy_type]
    params = config.get("params", {})

    try:
        return strategy_class(name=name, config=params)
    except ValueError as e:
        raise ConfigError(f"Invalid strategy config: {e}")


def _create_from_entry_conditions(config: dict[str, Any]) -> TradingStrategy:
    """
    Create strategy from YAML entry_conditions format.

    This handles the full strategy YAML format with entry_conditions list.
    """
    name = config.get("name", "unnamed")
    conditions = config.get("entry_conditions", [])
    trade_config = config.get("trade", {})

    if not conditions:
        raise ConfigError("Strategy must have at least one entry condition")

    # Build sub-strategies from conditions
    sub_strategies: list[TradingStrategy] = []

    for i, condition in enumerate(conditions):
        condition_type = condition.get("type")
        params = condition.get("params", {})

        if condition_type not in STRATEGY_TYPES:
            raise ConfigError(f"Unknown condition type: {condition_type}")

        # Merge trade config into params for strategies that need it
        if condition_type == "score_margin":
            params = {**params, **trade_config}

        strategy_class = STRATEGY_TYPES[condition_type]
        sub_strategy = strategy_class(name=f"{name}_condition_{i}", config=params)
        sub_strategies.append(sub_strategy)

    # If single condition, return it directly
    if len(sub_strategies) == 1:
        # Rename to match parent name
        strategy = sub_strategies[0]
        strategy.name = name
        return strategy

    # Multiple conditions - create composite with AND logic
    composite = CompositeStrategy(
        name=name,
        config={"operator": "and"},
        strategies=sub_strategies,
    )
    return composite


def load_strategy_from_file(path: Path) -> TradingStrategy:
    """
    Load a strategy from a YAML file.

    Args:
        path: Path to strategy YAML file

    Returns:
        Configured TradingStrategy instance

    Raises:
        ConfigError: If file is invalid
    """
    config = load_yaml_config(path)

    # Check if strategy is enabled
    if not config.get("enabled", True):
        raise ConfigError(f"Strategy '{config.get('name', path.stem)}' is disabled")

    return create_strategy_from_config(config)


def load_all_strategies(directory: Path) -> list[TradingStrategy]:
    """
    Load all enabled strategies from a directory.

    Args:
        directory: Path to strategies directory

    Returns:
        List of enabled strategy instances
    """
    strategies: list[TradingStrategy] = []

    if not directory.exists():
        return strategies

    for path in directory.glob("*.yaml"):
        try:
            strategy = load_strategy_from_file(path)
            strategies.append(strategy)
        except ConfigError:
            # Skip disabled or invalid strategies
            continue

    return strategies

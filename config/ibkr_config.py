"""
IBKR configuration module for NautilusTrader integration.

This module provides centralized configuration management for Interactive Brokers
connections, loading settings from environment variables and providing typed
configuration objects.
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


logger = logging.getLogger(__name__)

def load_env() -> None:
    """
    Load environment variables from .env file in the project root.
    
    This function should be called before accessing any environment variables
    to ensure they are loaded from the .env file.
    """
    load_dotenv()


@dataclass
class IBKRConfig:
    """
    Configuration object for IBKR connection parameters.
    
    Attributes:
        host: IBKR Gateway/TWS host address (typically 127.0.0.1)
        port: IBKR Gateway/TWS port (7497 for TWS paper, 4002 for Gateway paper)
        client_id: Unique client identifier for the connection
        account_id: IBKR account ID (paper trading accounts start with "DU")
        market_data_type: Market data type ("REALTIME", "DELAYED", "DELAYED_FROZEN")
    """
    host: str
    port: int
    client_id: int
    account_id: str
    market_data_type: str
    # IB symbology method for instrument resolution. Accepted values: IB_SIMPLIFIED, IB_RAW
    symbology_method: str = "IB_SIMPLIFIED"


def get_ibkr_config() -> IBKRConfig:
    """
    Load and validate IBKR configuration from environment variables.
    
    Returns:
        IBKRConfig: Configured IBKR connection parameters
        
    Raises:
        ValueError: If required environment variables are missing or invalid
        
    Environment Variables Required:
        IB_HOST: IBKR host address
        IB_PORT: IBKR port number
        IB_CLIENT_ID: Client identifier
        IB_ACCOUNT_ID: IBKR account ID (optional, defaults to empty string)
        IB_MARKET_DATA_TYPE: Market data type (optional, defaults to "REALTIME")
    """
    load_env()
    
    # Required variables
    host = os.getenv("IB_HOST")
    port_str = os.getenv("IB_PORT")
    client_id_str = os.getenv("IB_CLIENT_ID")
    
    if not host:
        raise ValueError("IB_HOST environment variable is required. Hint: Set IB_HOST=127.0.0.1 in .env file")
    if not port_str:
        raise ValueError(
            "IB_PORT environment variable is required. Hint: Set IB_PORT=7497 for TWS or IB_PORT=4002 for IB Gateway in .env file"
        )
    if not client_id_str:
        raise ValueError("IB_CLIENT_ID environment variable is required. Hint: Set IB_CLIENT_ID=1 (or another unique integer) in .env file")
    
    # Convert and validate numeric values
    try:
        port = int(port_str)
    except ValueError:
        raise ValueError(
            f"IB_PORT must be a valid integer, got: {port_str}. Common ports: 7497 (TWS paper), 4001 (TWS live), 4002 (Gateway paper)"
        )
    
    try:
        client_id = int(client_id_str)
    except ValueError:
        raise ValueError(
            f"IB_CLIENT_ID must be a valid positive integer, got: {client_id_str}. Each IB client connection must use a unique ID"
        )
    
    # Optional variables with defaults
    account_id = os.getenv("IB_ACCOUNT_ID", "")
    market_data_type = os.getenv("IB_MARKET_DATA_TYPE", "REALTIME")
    # Symbology method (controls how instruments are resolved with IBKR)
    raw_sym_method = (os.getenv("IB_SYMBOLOGY_METHOD", "IB_SIMPLIFIED") or "").strip().upper()
    if raw_sym_method not in {"IB_SIMPLIFIED", "IB_RAW"}:
        logger.warning(
            "Invalid IB_SYMBOLOGY_METHOD '%s'. Falling back to 'IB_SIMPLIFIED'. Accepted: IB_SIMPLIFIED, IB_RAW",
            raw_sym_method,
        )
        symbology_method = "IB_SIMPLIFIED"
    else:
        symbology_method = raw_sym_method
    
    config = IBKRConfig(
        host=host,
        port=port,
        client_id=client_id,
        account_id=account_id,
        market_data_type=market_data_type,
        symbology_method=symbology_method,
    )

    valid, message = validate_ibkr_config(config)
    if not valid:
        logger.warning("IBKR configuration warning: %s", message)

    logger.debug(
        "Loaded IBKR config: host=%s, port=%s, client_id=%s, market_data_type=%s, symbology_method=%s",
        config.host,
        config.port,
        config.client_id,
        config.market_data_type,
        config.symbology_method,
    )

    return config


def get_market_data_type_enum(market_data_type: str) -> int:
    """
    Convert market data type string to NautilusTrader's MarketDataTypeEnum value.
    
    Args:
        market_data_type: String representation of market data type
        
    Returns:
        int: Corresponding MarketDataTypeEnum value
        
    Market Data Types:
        REALTIME: 1 (live market data)
        DELAYED: 3 (delayed market data)
        DELAYED_FROZEN: 4 (delayed frozen market data, works without subscriptions)
    """
    mapping = {
        "REALTIME": 1,
        "DELAYED": 3,
        "DELAYED_FROZEN": 4
    }
    
    return mapping.get(market_data_type.upper(), 4)  # Default to DELAYED_FROZEN


def validate_ibkr_config(config: IBKRConfig) -> tuple[bool, str]:
    """Validate IBKR configuration values.

    Args:
        config: The IBKR configuration instance to validate.

    Returns:
        tuple[bool, str]: (is_valid, error_message). When valid, error_message is an empty string.
    """

    host = (config.host or "").strip()
    if not host:
        return False, "IB_HOST is empty. Ensure .env specifies a reachable host (e.g. 127.0.0.1)."

    if not (1024 <= config.port <= 65535):
        return False, "IB_PORT must be between 1024 and 65535 (examples: 7497 for TWS paper, 4002 for Gateway paper)."

    if config.client_id <= 0:
        return False, "IB_CLIENT_ID must be a positive integer and unique per connection."

    return True, ""

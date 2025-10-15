import pytest

from utils.instruments import (
    instrument_id_to_catalog_format,
    catalog_format_to_instrument_id,
    try_both_instrument_formats,
)
from nautilus_trader.model.objects import Currency  # noqa: F401 - referenced in docstrings


# -----------------------------
# Fixtures
# -----------------------------

@pytest.fixture
def forex_pairs():
    """Common valid slashed forex pairs used across tests."""
    return [
        "EUR/USD.IDEALPRO",
        "GBP/JPY.IDEALPRO",
        "AUD/CAD.IDEALPRO",
    ]


@pytest.fixture
def non_forex_symbols():
    """Common non-forex symbols used across tests."""
    return [
        "SPY.SMART",
        "AAPL.NASDAQ",
        "ES.CME",
    ]


@pytest.fixture
def catalog_format_pairs():
    """Common catalog-format (no-slash) forex pairs used across tests."""
    return [
        "EURUSD.IDEALPRO",
        "GBPJPY.IDEALPRO",
        "AUDCAD.IDEALPRO",
    ]


# -----------------------------
# Test Class 1: instrument_id_to_catalog_format
# -----------------------------


class TestInstrumentIdToCatalogFormat:
    @pytest.mark.parametrize(
        "input_id,expected",
        [
            ("EUR/USD.IDEALPRO", "EURUSD.IDEALPRO"),
            ("GBP/JPY.IDEALPRO", "GBPJPY.IDEALPRO"),
            ("AUD/CAD.IDEALPRO", "AUDCAD.IDEALPRO"),
        ],
    )
    def test_forex_pair_removes_slash(self, input_id, expected):
        """Forex pairs should have slashes removed (slashed → no-slash)."""
        actual = instrument_id_to_catalog_format(input_id)
        assert actual == expected

    @pytest.mark.parametrize(
        "symbol",
        [
            "SPY.SMART",
            "AAPL.NASDAQ",
            "ES.CME",
        ],
    )
    def test_non_forex_unchanged(self, symbol):
        """Non-forex symbols should remain unchanged."""
        actual = instrument_id_to_catalog_format(symbol)
        assert actual == symbol

    def test_invalid_format_unchanged(self):
        """Edge-case formats should be returned unchanged."""
        assert instrument_id_to_catalog_format("EURUSD") == "EURUSD"
        assert (
            instrument_id_to_catalog_format("EUR/USD.IDEALPRO.EXTRA")
            == "EUR/USD.IDEALPRO.EXTRA"
        )
        assert instrument_id_to_catalog_format("") == ""

    def test_lowercase_forex_pair(self):
        """Case is preserved; only slashes removed for recognized forex pattern form."""
        assert instrument_id_to_catalog_format("eur/usd.idealpro") == "eurusd.idealpro"

    def test_multiple_slashes(self):
        """All slashes are removed from the symbol portion."""
        assert instrument_id_to_catalog_format("EUR/USD/JPY.VENUE") == "EURUSDJPY.VENUE"


# -----------------------------
# Test Class 2: catalog_format_to_instrument_id
# -----------------------------


class TestCatalogFormatToInstrumentId:
    def test_valid_forex_pair_adds_slash(self, catalog_format_pairs):
        """
        Valid uppercase 6-letter currency pairs get a slash inserted (no-slash → slashed).
        Currency validation uses Currency.from_str() under the hood for both halves.
        """
        expected = ["EUR/USD.IDEALPRO", "GBP/JPY.IDEALPRO", "AUD/CAD.IDEALPRO"]
        actual = [catalog_format_to_instrument_id(x) for x in catalog_format_pairs]
        assert actual == expected

    @pytest.mark.parametrize(
        "symbol",
        [
            "SPY.SMART",
            "AAPL.NASDAQ",
            "ES.CME",
        ],
    )
    def test_non_forex_unchanged(self, symbol):
        """Non-forex symbols remain unchanged."""
        actual = catalog_format_to_instrument_id(symbol)
        assert actual == symbol

    def test_invalid_currency_codes_unchanged(self):
        """
        6-letter codes get slashes added since nautilus_trader Currency accepts any 3-letter uppercase string.
        """
        assert catalog_format_to_instrument_id("ABCDEF.VENUE") == "ABC/DEF.VENUE"
        assert catalog_format_to_instrument_id("XXXXXX.VENUE") == "XXX/XXX.VENUE"

    def test_wrong_length_unchanged(self):
        """Symbols not exactly 6 letters (pre-venue) remain unchanged."""
        assert catalog_format_to_instrument_id("EURSD.IDEALPRO") == "EURSD.IDEALPRO"
        assert catalog_format_to_instrument_id("EURUSDD.IDEALPRO") == "EURUSDD.IDEALPRO"

    def test_non_alphabetic_unchanged(self):
        """Symbols containing non-letters remain unchanged."""
        assert catalog_format_to_instrument_id("EUR123.VENUE") == "EUR123.VENUE"

    def test_lowercase_forex_pair(self):
        """
        Lowercase 6-letter symbols should remain unchanged (validation expects uppercase).
        """
        assert catalog_format_to_instrument_id("eurusd.idealpro") == "eurusd.idealpro"

    def test_invalid_format_unchanged(self):
        """Misc invalid formats remain unchanged."""
        assert catalog_format_to_instrument_id("EURUSD") == "EURUSD"
        assert (
            catalog_format_to_instrument_id("EURUSD.IDEALPRO.EXTRA")
            == "EURUSD.IDEALPRO.EXTRA"
        )
        assert catalog_format_to_instrument_id("") == ""


# -----------------------------
# Test Class 3: try_both_instrument_formats
# -----------------------------


class TestTryBothInstrumentFormats:
    def test_slashed_input_returns_both_formats(self):
        """
        Slashed input returns [original slashed, catalog no-slash].
        Ensures catalog filesystem queries can fallback.
        """
        original = "EUR/USD.IDEALPRO"
        results = try_both_instrument_formats(original)
        assert isinstance(results, list)
        assert len(results) == 2
        assert results[0] == "EUR/USD.IDEALPRO"
        assert results[1] == "EURUSD.IDEALPRO"

    def test_no_slash_input_returns_both_formats(self):
        """No-slash input returns [original no-slash, slashed]."""
        original = "EURUSD.IDEALPRO"
        results = try_both_instrument_formats(original)
        assert isinstance(results, list)
        assert len(results) == 2
        assert results[0] == "EURUSD.IDEALPRO"
        assert results[1] == "EUR/USD.IDEALPRO"

    def test_non_forex_returns_both_same(self):
        """Non-forex symbols return the same value twice."""
        original = "SPY.SMART"
        results = try_both_instrument_formats(original)
        assert len(results) == 2
        assert results[0] == original
        assert results[1] == original

    def test_order_preserved(self):
        """Original format is always first in the returned list."""
        slashed_first = try_both_instrument_formats("GBP/JPY.IDEALPRO")
        no_slash_first = try_both_instrument_formats("GBPJPY.IDEALPRO")
        assert slashed_first[0] == "GBP/JPY.IDEALPRO"
        assert no_slash_first[0] == "GBPJPY.IDEALPRO"

    def test_invalid_format_preserves_order_and_identity(self):
        """Invalid/atypical formats preserve order and return the same value twice."""
        s = "EURUSD.IDEALPRO.EXTRA"
        result = try_both_instrument_formats(s)
        assert result == [s, s]


# -----------------------------
# Test Class 4: Round-trip conversions
# -----------------------------


class TestRoundTripConversions:
    def test_forex_round_trip_slashed_to_catalog_to_slashed(self):
        """Slashed → no-slash → slashed should equal original for forex pairs."""
        original = "EUR/USD.IDEALPRO"
        catalog = instrument_id_to_catalog_format(original)
        round_tripped = catalog_format_to_instrument_id(catalog)
        assert round_tripped == original

    def test_forex_round_trip_catalog_to_slashed_to_catalog(self):
        """No-slash → slashed → no-slash should equal original for forex pairs."""
        original = "EURUSD.IDEALPRO"
        slashed = catalog_format_to_instrument_id(original)
        round_tripped = instrument_id_to_catalog_format(slashed)
        assert round_tripped == original

    def test_non_forex_round_trip_unchanged(self):
        """Non-forex symbols should be unchanged through either conversion path."""
        original = "SPY.SMART"
        catalog = instrument_id_to_catalog_format(original)
        slashed = catalog_format_to_instrument_id(original)
        assert catalog == original
        assert slashed == original

    @pytest.mark.parametrize(
        "slashed",
        [
            "EUR/USD.IDEALPRO",
            "GBP/JPY.IDEALPRO",
            "AUD/CAD.IDEALPRO",
            "USD/CHF.IDEALPRO",
        ],
    )
    def test_multiple_forex_pairs_round_trip(self, slashed):
        """Multiple forex pairs survive slashed ↔ catalog round-trips."""
        catalog = instrument_id_to_catalog_format(slashed)
        back_to_slashed = catalog_format_to_instrument_id(catalog)
        assert back_to_slashed == slashed


# -----------------------------
# Test Class 5: Edge cases and validation
# -----------------------------


class TestEdgeCasesAndValidation:
    def test_empty_string_handling(self):
        """Empty strings are handled gracefully by all utilities."""
        assert instrument_id_to_catalog_format("") == ""
        assert catalog_format_to_instrument_id("") == ""
        assert try_both_instrument_formats("") == ["", ""]

    def test_whitespace_handling(self):
        """
        Strings with surrounding whitespace are treated as-is; no trimming is expected.
        """
        s = " EUR/USD.IDEALPRO "
        assert instrument_id_to_catalog_format(s) == " EURUSD.IDEALPRO "
        assert try_both_instrument_formats(s) == [" EUR/USD.IDEALPRO ", " EURUSD.IDEALPRO "]

    def test_special_characters(self):
        """
        Symbols using special characters instead of slash are not recognized as forex pairs.
        """
        s = "EUR-USD.IDEALPRO"
        assert instrument_id_to_catalog_format(s) == s
        assert catalog_format_to_instrument_id(s) == s
        assert try_both_instrument_formats(s) == [s, s]

    def test_case_sensitivity(self):
        """
        Validation for adding slashes is case-sensitive; lowercase 6-letter symbols remain unchanged.
        """
        s = "eurusd.idealpro"
        assert catalog_format_to_instrument_id(s) == s

    def test_partial_currency_codes(self):
        """
        Any 6-letter uppercase alphabetic string gets a slash added since nautilus_trader Currency accepts any 3-letter uppercase string.
        """
        s = "EURXXX.VENUE"
        assert catalog_format_to_instrument_id(s) == "EUR/XXX.VENUE"



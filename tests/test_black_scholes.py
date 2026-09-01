import math

from app.backtest.black_scholes import call_delta, call_price, put_delta, put_price


def test_put_price_is_nonnegative_and_bounded_by_strike() -> None:
    price = put_price(spot=100, strike=95, time_to_expiry_years=30 / 365, volatility=0.25)

    assert price >= 0
    assert price <= 95


def test_put_price_at_zero_time_is_intrinsic_value() -> None:
    assert put_price(spot=90, strike=100, time_to_expiry_years=0, volatility=0.25) == 10
    assert put_price(spot=110, strike=100, time_to_expiry_years=0, volatility=0.25) == 0


def test_deeper_otm_put_has_smaller_price_and_delta_magnitude() -> None:
    near = put_price(spot=100, strike=98, time_to_expiry_years=30 / 365, volatility=0.25)
    far = put_price(spot=100, strike=80, time_to_expiry_years=30 / 365, volatility=0.25)
    assert far < near

    near_delta = put_delta(spot=100, strike=98, time_to_expiry_years=30 / 365, volatility=0.25)
    far_delta = put_delta(spot=100, strike=80, time_to_expiry_years=30 / 365, volatility=0.25)
    assert abs(far_delta) < abs(near_delta)


def test_put_delta_is_negative_and_bounded() -> None:
    delta = put_delta(spot=100, strike=95, time_to_expiry_years=30 / 365, volatility=0.25)

    assert -1.0 <= delta <= 0.0


def test_call_price_satisfies_put_call_parity() -> None:
    spot, strike, t, vol, rate = 100.0, 105.0, 30 / 365, 0.25, 0.04
    call = call_price(spot, strike, t, vol, rate)
    put = put_price(spot, strike, t, vol, rate)

    # C - P == S - K*e^-rT
    assert math.isclose(call - put, spot - strike * math.exp(-rate * t), rel_tol=1e-9, abs_tol=1e-9)


def test_call_price_at_zero_time_is_intrinsic_value() -> None:
    assert call_price(spot=110, strike=100, time_to_expiry_years=0, volatility=0.25) == 10
    assert call_price(spot=90, strike=100, time_to_expiry_years=0, volatility=0.25) == 0


def test_deeper_otm_call_has_smaller_price_and_delta() -> None:
    near = call_price(spot=100, strike=102, time_to_expiry_years=30 / 365, volatility=0.25)
    far = call_price(spot=100, strike=120, time_to_expiry_years=30 / 365, volatility=0.25)
    assert far < near

    assert call_delta(spot=100, strike=120, time_to_expiry_years=30 / 365, volatility=0.25) < call_delta(
        spot=100, strike=102, time_to_expiry_years=30 / 365, volatility=0.25
    )


def test_call_delta_is_positive_and_bounded() -> None:
    delta = call_delta(spot=100, strike=105, time_to_expiry_years=30 / 365, volatility=0.25)

    assert 0.0 <= delta <= 1.0


def test_bear_call_spread_is_a_credit() -> None:
    # Selling the nearer call and buying the further one must bring money in.
    t, vol = 21 / 365, 0.30
    credit = call_price(100, 105, t, vol) - call_price(100, 110, t, vol)

    assert credit > 0

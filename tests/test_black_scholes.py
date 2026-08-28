from app.backtest.black_scholes import put_delta, put_price


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

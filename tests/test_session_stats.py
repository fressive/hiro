from server.api.v1.endpoints.session import _token_usage_parts


def test_token_usage_parts_splits_cached_input_subset():
    assert _token_usage_parts(100, 75, 20) == {
        "input": 100,
        "uncached_input": 25,
        "cached": 75,
        "output": 20,
        "total": 120,
    }


def test_token_usage_parts_repairs_split_cached_input():
    assert _token_usage_parts(10, 30, 2) == {
        "input": 40,
        "uncached_input": 10,
        "cached": 30,
        "output": 2,
        "total": 42,
    }

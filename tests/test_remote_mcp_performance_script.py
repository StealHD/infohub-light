from scripts.benchmark_remote_mcp import _p95


def test_remote_mcp_benchmark_uses_a_nearest_rank_p95():
    values = [float(value) for value in range(1, 101)]

    assert _p95(values) == 95.0
    assert _p95([]) == 0.0

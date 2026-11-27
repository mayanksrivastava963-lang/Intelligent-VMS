import pytest
from scripts.capacity_plan import estimate


def test_storage_and_grid_bandwidth():
    result = estimate(16, 4, 0.5, 30, 2, 9)
    assert result["incoming_mbps"] == 72
    assert result["outgoing_grid_mbps"] == 9
    assert result["average_recording_MB_per_second"] == 8
    assert result["daily_storage_decimal_TB"] == pytest.approx(0.6912)
    assert result["retention_storage_decimal_TB_with_headroom"] == pytest.approx(26.9568)


@pytest.mark.parametrize("bitrate", [-1, 0, float("nan"), float("inf")])
def test_invalid_bitrate(bitrate):
    with pytest.raises(ValueError):
        estimate(4, bitrate, 0, 30, 1, 4)

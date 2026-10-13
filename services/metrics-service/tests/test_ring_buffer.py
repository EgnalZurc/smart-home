"""Unit tests for the in-memory ring buffer (storage.py)."""

from __future__ import annotations

from storage import RingBuffer


def test_add_and_series_roundtrip():
    rb = RingBuffer(maxlen=10)
    rb.add("host.ram.percent", "", 61.2, ts=100)
    rb.add("host.ram.percent", "", 62.0, ts=130)
    pts = rb.series("host.ram.percent")
    assert pts == [(100, 61.2), (130, 62.0)]


def test_maxlen_evicts_oldest():
    rb = RingBuffer(maxlen=3)
    for i in range(5):
        rb.add("m", "", float(i), ts=i)
    pts = rb.series("m")
    assert [v for (_ts, v) in pts] == [2.0, 3.0, 4.0]


def test_series_time_range_filter():
    rb = RingBuffer(maxlen=10)
    for i in range(10):
        rb.add("m", "", float(i), ts=i * 10)
    pts = rb.series("m", since=30, until=60)
    assert [ts for (ts, _v) in pts] == [30, 40, 50, 60]


def test_add_batch_shares_timestamp():
    rb = RingBuffer(maxlen=10)
    rb.add_batch([("host.cpu.percent", "", 10.0), ("host.ram.percent", "", 50.0)], ts=200)
    assert rb.series("host.cpu.percent") == [(200, 10.0)]
    assert rb.series("host.ram.percent") == [(200, 50.0)]


def test_latest_returns_newest_per_series():
    rb = RingBuffer(maxlen=10)
    rb.add("a", "", 1.0, ts=1)
    rb.add("a", "", 2.0, ts=2)
    rb.add("b", "x", 9.0, ts=3)
    latest = rb.latest()
    assert latest["a|"]["value"] == 2.0
    assert latest["a|"]["ts"] == 2
    assert latest["b|x"]["value"] == 9.0
    assert latest["b|x"]["label"] == "x"


def test_latest_skips_empty_and_distinct_labels():
    rb = RingBuffer(maxlen=10)
    rb.add("container.mem.percent", "svc1", 40.0, ts=1)
    rb.add("container.mem.percent", "svc2", 80.0, ts=1)
    latest = rb.latest()
    assert set(latest.keys()) == {
        "container.mem.percent|svc1",
        "container.mem.percent|svc2",
    }


def test_window_returns_values_in_half_open_range():
    rb = RingBuffer(maxlen=10)
    for i in range(6):
        rb.add("m", "", float(i), ts=i * 10)  # ts: 0,10,20,30,40,50
    win = rb.window(10, 40)  # [10, 40) -> ts 10,20,30
    assert win[("m", "")] == [1.0, 2.0, 3.0]


def test_keys_and_clear():
    rb = RingBuffer(maxlen=10)
    rb.add("a", "", 1.0, ts=1)
    rb.add("b", "l", 2.0, ts=1)
    assert set(rb.keys()) == {("a", ""), ("b", "l")}
    rb.clear()
    assert rb.keys() == []


def test_missing_series_returns_empty():
    rb = RingBuffer(maxlen=10)
    assert rb.series("nope") == []

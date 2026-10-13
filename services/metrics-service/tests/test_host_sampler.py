"""Unit tests for the host sampler (collector.py) using /proc fixture files."""

from __future__ import annotations

import collector

MEMINFO = """\
MemTotal:        4000000 kB
MemFree:          500000 kB
MemAvailable:    2000000 kB
Buffers:          100000 kB
Cached:           400000 kB
SReclaimable:      50000 kB
Shmem:             50000 kB
SwapTotal:       1000000 kB
SwapFree:         800000 kB
"""

STAT_1 = "cpu  100 0 100 800 0 0 0 0 0 0\n"
STAT_2 = "cpu  200 0 200 1200 0 0 0 0 0 0\n"
LOADAVG = "0.42 0.30 0.25 1/234 5678\n"
THERMAL = "52345\n"


def _write(path, content):
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_sample_memory_parses_ram_and_swap(tmp_path):
    p = _write(tmp_path / "meminfo", MEMINFO)
    samples = dict((m, v) for (m, _lbl, v) in collector.sample_memory(p))

    # used = total - free - buffers - max(0, cached+sreclaim-shmem)
    #      = 4,000,000 - 500,000 - 100,000 - 400,000 = 3,000,000 kB = ~2929.7 MB
    assert samples["host.ram.used_mb"] == round(3_000_000 / 1024, 1)
    assert samples["host.ram.percent"] == round(3_000_000 / 4_000_000 * 100, 1)
    # swap used = 1,000,000 - 800,000 = 200,000 kB
    assert samples["host.swap.used_mb"] == round(200_000 / 1024, 1)


def test_sample_memory_handles_zero_total(tmp_path):
    p = _write(tmp_path / "meminfo", "MemFree: 10 kB\n")
    samples = dict((m, v) for (m, _lbl, v) in collector.sample_memory(p))
    assert samples["host.ram.percent"] == 0.0


def test_sample_cpu_computes_percent(tmp_path, monkeypatch):
    # Two reads: first STAT_1, then STAT_2.
    reads = iter([STAT_1, STAT_2])

    def fake_read_cpu_times(path):
        line = next(reads)
        fields = [float(x) for x in line.split()[1:]]
        idle = fields[3]
        total = sum(fields)
        return total, idle

    monkeypatch.setattr(collector, "_read_cpu_times", fake_read_cpu_times)
    monkeypatch.setattr(collector.time, "sleep", lambda _s: None)

    samples = dict((m, v) for (m, _lbl, v) in collector.sample_cpu("ignored", 0.0))
    # total delta = (200+200+1200) - (100+100+800) = 1600-1000 = 600
    # idle delta  = 1200 - 800 = 400 -> busy = 1 - 400/600 = 0.333 -> 33.3%
    assert samples["host.cpu.percent"] == 33.3


def test_sample_temp_divides_by_1000(tmp_path):
    p = _write(tmp_path / "temp", THERMAL)
    samples = dict((m, v) for (m, _lbl, v) in collector.sample_temp(p))
    assert samples["host.temp.celsius"] == 52.3


def test_sample_load_reads_1m(tmp_path):
    p = _write(tmp_path / "loadavg", LOADAVG)
    samples = dict((m, v) for (m, _lbl, v) in collector.sample_load(p))
    assert samples["host.load.1m"] == 0.42


def test_sample_disk_returns_percent(monkeypatch):
    import os

    class FakeStat:
        f_frsize = 4096
        f_blocks = 1000
        f_bavail = 250

    monkeypatch.setattr(os, "statvfs", lambda _p: FakeStat())
    samples = dict((m, v) for (m, _lbl, v) in collector.sample_disk("/"))
    # used = (1000-250)/1000 = 75%
    assert samples["host.disk.percent"] == 75.0


def test_sample_host_tolerates_sampler_failure(monkeypatch, tmp_path):
    # Point meminfo at a valid file but make temp read a missing path so that
    # sampler raises and is swallowed, yet the others still produce samples.
    monkeypatch.setattr(collector, "PROC_MEMINFO", _write(tmp_path / "mi", MEMINFO))
    monkeypatch.setattr(
        collector, "sample_cpu", lambda *a, **k: [("host.cpu.percent", "", 1.0)]
    )
    monkeypatch.setattr(collector, "THERMAL_ZONE", str(tmp_path / "does-not-exist"))
    monkeypatch.setattr(collector, "PROC_LOADAVG", _write(tmp_path / "la", LOADAVG))

    import os

    class FakeStat:
        f_frsize = 4096
        f_blocks = 100
        f_bavail = 50

    monkeypatch.setattr(os, "statvfs", lambda _p: FakeStat())

    metrics = {m for (m, _lbl, _v) in collector.sample_host()}
    assert "host.ram.used_mb" in metrics
    assert "host.disk.percent" in metrics
    assert "host.load.1m" in metrics
    # temp sampler failed and was swallowed
    assert "host.temp.celsius" not in metrics

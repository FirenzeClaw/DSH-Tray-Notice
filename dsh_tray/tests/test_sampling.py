"""进程采样测试：CPU 求差、首次为 None、RSS、进程消失。

采样必须自采（不走插件上报）——DSH 卡死时正是最需要看进程的时候。这也意味着
它必须能容忍「读不到」：进程刚好退出、/proc 权限不足、字段被截断，都不该抛错。
"""

from __future__ import annotations

import unittest

from dsh_tray.notify.sampling import CpuTracker, parse_rss_bytes, parse_stat, sample_rows


class StatParsingTest(unittest.TestCase):
    """`/proc/<pid>/stat` 解析。"""

    def test_parses_ticks_and_starttime(self) -> None:
        # comm 里带空格与括号，是最容易切错的情形
        line = "1234 (dsh web (main)) S 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21"
        parsed = parse_stat(line)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], 11 + 12)  # utime + stime
        self.assertEqual(parsed[1], 19)  # starttime

    def test_returns_none_on_short_line(self) -> None:
        self.assertIsNone(parse_stat("1234 (x) S 1 2"))

    def test_returns_none_without_paren(self) -> None:
        self.assertIsNone(parse_stat("garbage"))


class RssParsingTest(unittest.TestCase):
    """VmRSS 解析。"""

    def test_parses_kilobytes_to_bytes(self) -> None:
        status = "Name:\tdsh\nVmRSS:\t  20480 kB\n"
        self.assertEqual(parse_rss_bytes(status), 20480 * 1024)

    def test_missing_vmrss_is_zero(self) -> None:
        self.assertEqual(parse_rss_bytes("Name:\tdsh\n"), 0)

    def test_bad_value_is_zero(self) -> None:
        self.assertEqual(parse_rss_bytes("VmRSS:\tnotanumber kB\n"), 0)


class CpuTrackerTest(unittest.TestCase):
    """CPU 百分比求差。"""

    def test_first_sample_is_none(self) -> None:
        tracker = CpuTracker(clock_ticks=100)
        self.assertIsNone(tracker.update(pid=1, ticks=500.0, elapsed_seconds=1.0))

    def test_second_sample_computes_percent(self) -> None:
        tracker = CpuTracker(clock_ticks=100)
        tracker.update(pid=1, ticks=500.0, elapsed_seconds=1.0)
        # 1 秒内多用了 50 ticks = 0.5 秒 CPU = 50%
        percent = tracker.update(pid=1, ticks=550.0, elapsed_seconds=1.0)
        self.assertIsNotNone(percent)
        assert percent is not None
        self.assertAlmostEqual(percent, 50.0, places=1)

    def test_forgets_dead_pids(self) -> None:
        tracker = CpuTracker(clock_ticks=100)
        tracker.update(pid=1, ticks=500.0, elapsed_seconds=1.0)
        tracker.forget({2})
        self.assertIsNone(tracker.update(pid=1, ticks=550.0, elapsed_seconds=1.0), "被遗忘的 pid 应重新算首采")

    def test_never_negative(self) -> None:
        tracker = CpuTracker(clock_ticks=100)
        tracker.update(pid=1, ticks=500.0, elapsed_seconds=1.0)
        self.assertEqual(tracker.update(pid=1, ticks=400.0, elapsed_seconds=1.0), 0.0)


class SampleRowsTest(unittest.TestCase):
    """整体采样：进程消失不报错。"""

    def test_missing_proc_yields_no_row(self) -> None:
        rows = sample_rows([999_999_999], read_stat=lambda pid: None, read_rss=lambda pid: 0)
        self.assertEqual(rows, [])

    def test_rows_carry_pid_and_role(self) -> None:
        def fake_stat(pid: int):
            return (100.0, 10.0)

        rows = sample_rows(
            [4242],
            read_stat=fake_stat,
            read_rss=lambda pid: 1024,
            classify=lambda pid: ("core", "dsh web"),
            clock_ticks=100,
            uptime=1000.0,
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.pid, 4242)
        self.assertEqual(row.role, "core")
        self.assertEqual(row.label, "dsh web")
        self.assertEqual(row.rss_bytes, 1024)
        self.assertEqual(row.age_seconds, 999)

    def test_total_helpers(self) -> None:
        from dsh_tray.notify.sampling import SampleSummary

        summary = SampleSummary.from_rows(
            [
                _row(1, 10.0, 100),
                _row(2, None, 200),
            ]
        )
        self.assertEqual(summary.cpu_percent, 10.0, "None 不该参与求和")
        self.assertEqual(summary.rss_bytes, 300)
        self.assertEqual(summary.process_count, 2)


def _row(pid: int, cpu: float | None, rss: int):
    """造一行采样。"""
    from dsh_tray.notify.sampling import ProcessRow

    return ProcessRow(pid=pid, role="tool", label="x", cpu_percent=cpu, rss_bytes=rss, age_seconds=1)


if __name__ == "__main__":
    unittest.main()

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest
from app.api.schemas import StartRunRequest
from app.runtime.manager import _RunContext


class TickCadenceTest(unittest.TestCase):
    def test_ten_seconds_subtracts_processing_time(self):
        start = datetime(2026, 9, 9, tzinfo=timezone.utc)
        context = SimpleNamespace(tick_interval_seconds=10, interval_minutes=10, speed=60,
            stop_event=Mock(), process_tick=Mock(), finish=Mock(), _closed=False,
            state=SimpleNamespace(current_observed_at=start), producer=SimpleNamespace(end_at=start+timedelta(hours=1)))
        context.stop_event.is_set.return_value = False
        context.stop_event.wait.return_value = True
        with patch('app.runtime.manager.time.monotonic', side_effect=[100, 102]):
            _RunContext.run_loop(context)
        context.stop_event.wait.assert_called_once_with(8)
        context.finish.assert_called_once_with('stopped')

    def test_overrun_skips_burst(self):
        start = datetime(2026, 9, 9, tzinfo=timezone.utc)
        context = SimpleNamespace(tick_interval_seconds=10, interval_minutes=10, speed=60,
            stop_event=Mock(), process_tick=Mock(), finish=Mock(), _closed=False,
            state=SimpleNamespace(current_observed_at=start), producer=SimpleNamespace(end_at=start+timedelta(hours=1)))
        context.stop_event.is_set.return_value = False
        context.stop_event.wait.return_value = True
        with patch('app.runtime.manager.time.monotonic', side_effect=[100, 125]):
            _RunContext.run_loop(context)
        context.stop_event.wait.assert_called_once_with(5)

    def test_request_keeps_legacy_speed_when_not_explicit(self):
        self.assertIsNone(StartRunRequest().tick_interval_seconds)
        self.assertEqual(StartRunRequest(tick_interval_seconds=10).tick_interval_seconds, 10)

import tempfile
import unittest
from pathlib import Path

from approval_agent.lease import LeaseStore


class LeaseTests(unittest.TestCase):
    def test_ttl_survives_restart_and_watchdog_rotates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            now = [1000.0]
            changes = []
            first = LeaseStore(changes.append, path, lambda: now[0])
            temporary, expires = first.issue(30)
            self.assertEqual(expires, 1030.0)
            self.assertEqual(changes, [temporary])
            self.assertNotIn(temporary, (path / "state.json").read_text())
            restarted_watchdog = LeaseStore(changes.append, path, lambda: now[0])
            now[0] = 1029.0
            self.assertFalse(restarted_watchdog.expire_if_due())
            now[0] = 1030.0
            self.assertTrue(restarted_watchdog.expire_if_due())
            self.assertNotEqual(changes[-1], temporary)
            self.assertFalse(restarted_watchdog.expire_if_due())
            self.assertIsNone(restarted_watchdog.active_until())

    def test_second_issue_is_refused_until_first_expires(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1000.0]
            changes = []
            store = LeaseStore(changes.append, Path(directory), lambda: now[0])
            first, _ = store.issue(60)
            with self.assertRaises(RuntimeError):
                store.issue(60)
            self.assertEqual(changes, [first])
            now[0] = 1060.0
            second, _ = store.issue(60)
            self.assertNotEqual(second, first)
            self.assertNotEqual(changes[-2], first)

    def test_invalid_ttl_does_not_touch_account(self):
        with tempfile.TemporaryDirectory() as directory:
            changes = []
            store = LeaseStore(changes.append, Path(directory))
            with self.assertRaises(ValueError):
                store.issue(31 * 60)
            self.assertEqual(changes, [])

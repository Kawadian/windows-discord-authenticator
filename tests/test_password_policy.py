import json
import tempfile
import unittest
from pathlib import Path

from approval_agent.config import Config
from approval_agent.lease import DIGITS, LOWER, SYMBOLS, UPPER, LeaseStore, password


class PasswordPolicyTests(unittest.TestCase):
    def test_existing_config_uses_private_lowercase_alphanumeric_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'config.json').write_text(json.dumps({
                'bot_token': 'test', 'channel_id': 123, 'owner_id': 456,
            }), encoding='utf-8')
            config = Config.load(path / 'config.json')
            self.assertEqual(config.password_length, 10)
            self.assertFalse(config.ttl_change_public or config.password_public or config.expiry_public)
            changes = []
            secret, _ = LeaseStore(changes.append, path, lambda: 1000, config).issue(30)
            self.assertEqual(len(secret), 10)
            self.assertTrue(any(char in DIGITS for char in secret))
            self.assertTrue(any(char in LOWER for char in secret))
            self.assertTrue(all(char in DIGITS + LOWER for char in secret))
            self.assertEqual(changes, [secret])

    def test_every_enabled_character_set_is_present(self):
        for _ in range(30):
            secret = password(12, digits=True, letters=True, letter_case='both', symbols=True)
            self.assertEqual(len(secret), 12)
            for alphabet in (DIGITS, LOWER, UPPER, SYMBOLS):
                self.assertTrue(any(char in alphabet for char in secret))
        self.assertTrue(set(password(10, digits=False, letters=True, letter_case='upper')) <= set(UPPER))
        self.assertTrue(set(password(10, digits=False, letters=False, symbols=True)) <= set(SYMBOLS))

    def test_invalid_policy_is_rejected_before_account_change(self):
        with tempfile.TemporaryDirectory() as directory:
            for overrides in ({'password_length': 7}, {'password_length': 65},
                              {'password_digits': False, 'password_letters': False, 'password_symbols': False},
                              {'password_letter_case': 'invalid'}, {'password_public': 'yes'}):
                config = Config('test', 123, 456, **overrides)
                changes = []
                store = LeaseStore(changes.append, Path(directory), lambda: 1000, config)
                with self.assertRaises(ValueError):
                    store.issue(30)
                self.assertEqual(changes, [])

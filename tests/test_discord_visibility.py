import time
import unittest
from unittest.mock import AsyncMock, Mock

from approval_agent.discord_ui import ApprovalRequest, ApprovalView, TtlSelect


class DiscordVisibilityTests(unittest.IsolatedAsyncioTestCase):
    def new_view(self, **visibility):
        request = ApprovalRequest('id', 'manual', 'PC', 'user', 'window', 'process',
                                  'time', None, time.time())
        store = Mock()
        store.issue.return_value = ('abc234def5', time.time() + 60)
        view = ApprovalView(123, 'UacApproval', request, store, 300, **visibility)
        interaction = Mock()
        interaction.user.id = 123
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock(side_effect=[Mock(delete=AsyncMock()), Mock(delete=AsyncMock())])
        interaction.message.content = '申請'
        interaction.message.edit = AsyncMock()
        return view, store, interaction

    async def test_password_and_expiry_have_independent_visibility(self):
        for password_public, expiry_public in ((False, False), (True, False),
                                               (False, True), (True, True)):
            with self.subTest(password_public=password_public, expiry_public=expiry_public):
                view, store, interaction = self.new_view(
                    password_public=password_public, expiry_public=expiry_public)
                button = next(item for item in view.children if item.label == '一時パスワードを発行')
                await button.callback(interaction)
                first, second = interaction.followup.send.call_args_list
                self.assertEqual(first.kwargs['ephemeral'], not password_public)
                self.assertEqual(second.kwargs['ephemeral'], not expiry_public)
                self.assertIn('abc234def5', first.args[0])
                self.assertNotIn('abc234def5', second.args[0])
                self.assertTrue(view.completed)
                store.rotate.assert_not_called()

    async def test_ttl_change_visibility(self):
        for public in (False, True):
            view, _, interaction = self.new_view(ttl_change_public=public)
            select = next(item for item in view.children if isinstance(item, TtlSelect))
            select._values = ['60']
            await select.callback(interaction)
            self.assertEqual(interaction.response.send_message.call_args.kwargs['ephemeral'], not public)

    async def test_partial_delivery_revokes_and_deletes_first_message(self):
        view, store, interaction = self.new_view(password_public=True)
        first = Mock(delete=AsyncMock())
        interaction.followup.send.side_effect = [first, RuntimeError('delivery failed')]
        button = next(item for item in view.children if item.label == '一時パスワードを発行')
        with self.assertRaises(RuntimeError):
            await button.callback(interaction)
        store.rotate.assert_called_once()
        first.delete.assert_awaited_once()

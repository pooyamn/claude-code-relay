"""Observer fixtures: no profile, daemon, network or model is used."""
import unittest
from unittest import mock

import pc_codex_daemon_status as observer


class StatusTests(unittest.TestCase):
    def fixture(self, *, state='connected', foreign=False):
        channel = mock.Mock()
        replies = [
            {'id': 1, 'result': {}},
            {'method': 'item/commandExecution/requestApproval', 'id': 99, 'params': {'private': 'not mirrored'}},
            {'id': 2, 'result': {'account': {'type': 'chatgpt', 'email': 'fixture@example.invalid'}}},
            {'id': 30 if foreign else 3, 'result': {'status': state, 'serverName': 'Fixture',
                                                 'installationId': 'fixture-install', 'environmentId': 'fixture-env'}},
            {'id': 4, 'result': {'data': []}},
        ]
        channel.receive.side_effect = [(value, b'') for value in replies]
        return channel, mock.Mock(), {'uid': 1000, 'peerUid': 1000, 'peerPid': 123}

    def test_exact_reads_only_no_answers_auth_or_model_actions(self):
        channel, verify, metadata = self.fixture()
        with mock.patch.object(observer, 'connect', return_value=(channel, verify, metadata)), \
                mock.patch.object(observer.Path, 'exists', return_value=False):
            result = observer.observe()
        self.assertEqual([call.args[0]['method'] for call in channel.send.call_args_list],
                         ['initialize', 'initialized', 'account/read', 'remoteControl/status/read', 'thread/loaded/list'])
        self.assertEqual(channel.send.call_args_list[2].args[0]['params'], {'refreshToken': False})
        self.assertNotIn('email', result)
        self.assertIs(result['modelsStarted'], False)
        self.assertIs(result['phoneRoundTripVerified'], False)
        self.assertIs(result['packageAutoUpdateEnabled'], False)
        channel.close.assert_called_once()

    def test_foreign_receipt_closes_without_retry(self):
        channel, verify, metadata = self.fixture(foreign=True)
        with mock.patch.object(observer, 'connect', return_value=(channel, verify, metadata)), self.assertRaises(ValueError):
            observer.observe()
        self.assertEqual(channel.send.call_count, 4)
        channel.close.assert_called_once()

    def test_unknown_remote_state_is_not_reported_healthy(self):
        channel, verify, metadata = self.fixture(state='invented')
        with mock.patch.object(observer, 'connect', return_value=(channel, verify, metadata)), self.assertRaises(ValueError):
            observer.observe()
        channel.close.assert_called_once()

    def test_lost_read_receipt_is_not_replayed(self):
        channel, verify, metadata = self.fixture()
        channel.receive.side_effect = TimeoutError
        with mock.patch.object(observer, 'connect', return_value=(channel, verify, metadata)), self.assertRaises(TimeoutError):
            observer.observe()
        self.assertEqual(channel.send.call_count, 1)
        channel.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()

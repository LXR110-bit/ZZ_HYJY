import unittest
from unittest.mock import Mock, patch

import main
from services.feishu import VcLookupError


def _event(topic="某会", owner="ou_stranger", meeting_id="m1"):
    ev = Mock()
    ev.event.meeting.topic = topic
    ev.event.meeting.id = meeting_id
    ev.event.meeting.owner.id.open_id = owner
    ev.event.meeting.host_user.id.open_id = owner
    return ev


class TestGate(unittest.TestCase):
    @patch("main.MEETING_OWNER_WHITELIST", {"ou_a6cee6c6461d5ba265b68fea58f89b3a"})
    @patch("main.threading.Thread")
    @patch("main.did_user_attend", return_value=(True, "participants=8 attended=True"))
    def test_attended_starts_thread(self, _att, mthread):
        main.on_meeting_ended(_event())
        mthread.assert_called_once()
        self.assertEqual(mthread.call_args.kwargs["kwargs"]["meeting_id"], "m1")

    @patch("main.MEETING_OWNER_WHITELIST", {"ou_a6cee6c6461d5ba265b68fea58f89b3a"})
    @patch("main.threading.Thread")
    @patch("main.did_user_attend", return_value=(False, "participants=11 attended=False"))
    def test_not_attended_skips(self, _att, mthread):
        main.on_meeting_ended(_event())
        mthread.assert_not_called()

    @patch("main.MEETING_OWNER_WHITELIST", {"ou_a6cee6c6461d5ba265b68fea58f89b3a"})
    @patch("main.threading.Thread")
    @patch("main.did_user_attend", side_effect=VcLookupError("api down"))
    def test_vc_error_fails_closed(self, _att, mthread):
        # fail-closed：165 场/小时的量级下 fail-open 会炸出大量无效线程。
        main.on_meeting_ended(_event())
        mthread.assert_not_called()

    @patch("main.MEETING_OWNER_WHITELIST", {"ou_a6cee6c6461d5ba265b68fea58f89b3a"})
    @patch("main.threading.Thread")
    @patch("main.did_user_attend")
    def test_whitelist_owner_bypasses_vc_call(self, matt, mthread):
        main.on_meeting_ended(_event(owner="ou_a6cee6c6461d5ba265b68fea58f89b3a"))
        matt.assert_not_called()
        mthread.assert_called_once()


if __name__ == "__main__":
    unittest.main()

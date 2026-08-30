import unittest
from unittest.mock import Mock, patch

from config import AUTHORIZED_USER_OPEN_ID
from services import feishu

U = AUTHORIZED_USER_OPEN_ID


def _resp(payload, status=200):
    m = Mock()
    m.status_code = status
    m.json.return_value = payload
    return m


def _meeting(participants):
    return {"code": 0, "data": {"meeting": {"id": "m1", "participants": participants}}}


class TestDidUserAttend(unittest.TestCase):
    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_attended(self, mget, _h):
        mget.return_value = _resp(_meeting([{"id": "ou_other"}, {"id": U}]))
        attended, evidence = feishu.did_user_attend("m1")
        self.assertTrue(attended)
        self.assertIn("participants=2", evidence)

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_not_attended(self, mget, _h):
        mget.return_value = _resp(_meeting([{"id": "ou_a"}, {"id": "ou_b"}]))
        attended, evidence = feishu.did_user_attend("m1")
        self.assertFalse(attended)
        self.assertIn("attended=False", evidence)

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_dedups_repeated_participant(self, mget, _h):
        # 复刻 2026-08-26 诺曼底品类簇周会：host 在列表里出现两次，
        # participant_count=10 而列表长度 11。不去重会把人数报错。
        mget.return_value = _resp(_meeting([
            {"id": "ou_host"}, {"id": "ou_x"}, {"id": "ou_host"},
        ]))
        attended, evidence = feishu.did_user_attend("m1")
        self.assertFalse(attended)
        self.assertIn("participants=2", evidence)

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_empty_participants(self, mget, _h):
        mget.return_value = _resp(_meeting([]))
        attended, evidence = feishu.did_user_attend("m1")
        self.assertFalse(attended)
        self.assertIn("participants=0", evidence)

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_missing_participants_key(self, mget, _h):
        mget.return_value = _resp({"code": 0, "data": {"meeting": {"id": "m1"}}})
        attended, evidence = feishu.did_user_attend("m1")
        self.assertFalse(attended)
        self.assertIn("participants=0", evidence)

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_nonzero_code_raises(self, mget, _h):
        mget.return_value = _resp({"code": 1000, "msg": "boom"}, status=400)
        with self.assertRaises(feishu.VcLookupError):
            feishu.did_user_attend("m1")

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_participant_without_id_ignored(self, mget, _h):
        mget.return_value = _resp(_meeting([{"id": U}, {"user_type": 1}]))
        attended, evidence = feishu.did_user_attend("m1")
        self.assertTrue(attended)
        self.assertIn("participants=1", evidence)


if __name__ == "__main__":
    unittest.main()

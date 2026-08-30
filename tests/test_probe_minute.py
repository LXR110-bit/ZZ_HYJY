import unittest
from unittest.mock import Mock, patch

from services import feishu


def _resp(payload, status=200):
    m = Mock()
    m.status_code = status
    m.json.return_value = payload
    return m


class TestProbeMinuteReadable(unittest.TestCase):
    @patch("services.feishu._user_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_readable_returns_owner_and_title(self, mget, _h):
        mget.return_value = _resp({
            "code": 0,
            "data": {"minute": {
                "owner_id": "ou_a6cee6c6461d5ba265b68fea58f89b3a",
                "title": "李肖然的视频会议",
            }},
        })
        state, detail = feishu.probe_minute_readable("obcnmxf8jubzzqtp5914vw9l")
        self.assertEqual(state, "readable")
        self.assertEqual(detail["owner_id"], "ou_a6cee6c6461d5ba265b68fea58f89b3a")
        self.assertEqual(detail["title"], "李肖然的视频会议")

    @patch("services.feishu._user_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_2091005_is_forbidden_not_error(self, mget, _h):
        # 这一条是整个修复的关键：2091005 必须被识别为"无权限，别再等了"，
        # 而不是"还没生成好，继续轮询"。
        mget.return_value = _resp(
            {"code": 2091005, "msg": "permission deny"}, status=403
        )
        state, detail = feishu.probe_minute_readable("obcnnhq74693846xhxg9ugb2")
        self.assertEqual(state, "forbidden")
        self.assertEqual(detail["code"], 2091005)

    @patch("services.feishu._user_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_other_code_is_error(self, mget, _h):
        mget.return_value = _resp({"code": 99991679, "msg": "unauthorized"}, status=400)
        state, detail = feishu.probe_minute_readable("t")
        self.assertEqual(state, "error")
        self.assertEqual(detail["code"], 99991679)

    @patch("services.feishu._user_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_non_json_is_error(self, mget, _h):
        m = Mock()
        m.status_code = 502
        m.json.side_effect = ValueError("no json")
        mget.return_value = m
        state, detail = feishu.probe_minute_readable("t")
        self.assertEqual(state, "error")
        self.assertIsNone(detail["code"])

    @patch("services.feishu._user_headers", return_value={})
    @patch("services.feishu.requests.get")
    def test_readable_with_missing_fields(self, mget, _h):
        mget.return_value = _resp({"code": 0, "data": {}})
        state, detail = feishu.probe_minute_readable("t")
        self.assertEqual(state, "readable")
        self.assertEqual(detail["owner_id"], "")
        self.assertEqual(detail["title"], "")


if __name__ == "__main__":
    unittest.main()

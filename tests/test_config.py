import importlib
import os
import unittest


class TestConfig(unittest.TestCase):
    def test_authorized_user_default(self):
        import config
        importlib.reload(config)
        self.assertEqual(
            config.AUTHORIZED_USER_OPEN_ID,
            "ou_a6cee6c6461d5ba265b68fea58f89b3a",
        )

    def test_dry_run_defaults_false(self):
        os.environ.pop("DRY_RUN", None)
        import config
        importlib.reload(config)
        self.assertIs(config.DRY_RUN, False)

    def test_dry_run_truthy_values(self):
        import config
        for raw in ("1", "true", "True", "yes"):
            os.environ["DRY_RUN"] = raw
            importlib.reload(config)
            self.assertIs(config.DRY_RUN, True, f"DRY_RUN={raw!r} 应为 True")
        os.environ.pop("DRY_RUN", None)
        importlib.reload(config)


if __name__ == "__main__":
    unittest.main()

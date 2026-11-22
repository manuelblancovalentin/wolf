import contextlib
import io
import unittest
from unittest import mock

from wolf.cli import build_parser
from wolf.commands.upgrade import command_upgrade


class UpgradeCommandTests(unittest.TestCase):
    def test_already_latest_reports_so_and_installs_nothing(self):
        args = mock.Mock(check=False, yes=False)
        with mock.patch(
            "wolf.commands.upgrade.check_latest", return_value=("0.1.0", "0.1.0", False),
        ), mock.patch("wolf.commands.upgrade.download_and_install") as install:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                result = command_upgrade(args)
        self.assertEqual(result, 0)
        install.assert_not_called()

    def test_check_only_reports_and_never_installs(self):
        args = mock.Mock(check=True, yes=False)
        with mock.patch(
            "wolf.commands.upgrade.check_latest", return_value=("0.1.0", "0.2.0", True),
        ), mock.patch("wolf.commands.upgrade.download_and_install") as install:
            result = command_upgrade(args)
        self.assertEqual(result, 0)
        install.assert_not_called()

    def test_declining_the_prompt_installs_nothing(self):
        args = mock.Mock(check=False, yes=False)
        with mock.patch(
            "wolf.commands.upgrade.check_latest", return_value=("0.1.0", "0.2.0", True),
        ), mock.patch("wolf.commands.upgrade.download_and_install") as install, mock.patch(
            "wolf.commands.upgrade.ui.confirm", return_value=False,
        ):
            result = command_upgrade(args)
        self.assertEqual(result, 0)
        install.assert_not_called()

    def test_yes_skips_the_prompt_and_installs(self):
        args = mock.Mock(check=False, yes=True)
        with mock.patch(
            "wolf.commands.upgrade.check_latest", return_value=("0.1.0", "0.2.0", True),
        ), mock.patch(
            "wolf.commands.upgrade.download_and_install", return_value="0.2.0",
        ) as install:
            result = command_upgrade(args)
        self.assertEqual(result, 0)
        install.assert_called_once()

    def test_a_check_failure_reports_an_error_and_exits_nonzero(self):
        from wolf.upgrade import UpgradeError

        args = mock.Mock(check=False, yes=False)
        with mock.patch(
            "wolf.commands.upgrade.check_latest", side_effect=UpgradeError("cannot reach the releases API"),
        ):
            result = command_upgrade(args)
        self.assertEqual(result, 1)

    def test_an_install_failure_reports_an_error_and_exits_nonzero(self):
        from wolf.upgrade import UpgradeError

        args = mock.Mock(check=False, yes=True)
        with mock.patch(
            "wolf.commands.upgrade.check_latest", return_value=("0.1.0", "0.2.0", True),
        ), mock.patch(
            "wolf.commands.upgrade.download_and_install", side_effect=UpgradeError("pip install failed"),
        ):
            result = command_upgrade(args)
        self.assertEqual(result, 1)

    def test_upgrade_is_registered_with_check_and_yes_flags(self):
        parser = build_parser()
        args = parser.parse_args(["upgrade", "--check"])
        self.assertTrue(args.check)
        args = parser.parse_args(["upgrade", "-y"])
        self.assertTrue(args.yes)


if __name__ == "__main__":
    unittest.main()

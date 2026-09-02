import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash") or "/bin/bash"
ZSH = shutil.which("zsh")


class BashIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wolf-shell-")
        self.root = Path(self.temporary.name)
        (self.root / "envs" / "foo").mkdir(parents=True)
        (self.root / "envs" / "bar").mkdir()
        for name in ("foo", "bar"):
            (self.root / "envs" / name / "vars.env").write_text(
                'DESIGN_NAME="ibex"\nPROCESS="asap7"\nBACKEND="orfs"\nWORKSPACE_DIR="work"\n'
            )
        self.env = os.environ.copy()
        self.env.update({"WOLF_HOME": str(self.root), "PYTHONPATH": str(REPO_ROOT / "src")})

    def tearDown(self):
        self.temporary.cleanup()

    def bash(self, script):
        return subprocess.run([BASH, "--noprofile", "--norc", "-c", script], env=self.env,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    def test_activation_is_in_place_and_restores_state(self):
        result = self.bash(
            f'''source "{REPO_ROOT}/shell/wolf.bash"
original_pid=$$; original_pwd=$PWD; original_path=$PATH; original_ps1='custom> '; PS1=$original_ps1; KEEP=value
wolf activate foo || exit $?
[ "$$" = "$original_pid" ] && [ "$PWD" = "$original_pwd" ] && [ "$PATH" = "$original_path" ] && [ "$KEEP" = value ] && [ "$WOLF_ACTIVE_ENV" = foo ] || exit 10
wolf activate bar || exit $?
[ "$WOLF_ACTIVE_ENV" = bar ] && [ "$PS1" = 'custom>  [bar]' ] || exit 11
wolf info >/dev/null || exit $?
cd /; wolf run --plan >/dev/null || exit $?
wolf deactivate
[ -z "${{WOLF_ACTIVE_ENV+x}}" ] && [ "$PS1" = "$original_ps1" ] && [ "$$" = "$original_pid" ] && [ "$KEEP" = value ] || exit 12
'''
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_invalid_activation_and_inactive_deactivation_are_safe(self):
        result = self.bash(
            f'''source "{REPO_ROOT}/shell/wolf.bash"
PS1='original> '; wolf activate missing; status=$?
[ $status -ne 0 ] && [ -z "${{WOLF_ACTIVE_ENV+x}}" ] && [ "$PS1" = 'original> ' ] || exit 10
wolf deactivate
'''
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


@unittest.skipUnless(ZSH, "zsh is not installed")
class ZshIntegrationTests(BashIntegrationTests):
    def zsh(self, script):
        return subprocess.run([ZSH, "-f", "-c", script], env=self.env,
                              text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    def test_activation_marks_theme_managed_prompt_and_restores_it(self):
        result = self.zsh(
            f'''source "{REPO_ROOT}/shell/wolf.zsh"
original_pid=$$; original_pwd=$PWD; original_path=$PATH; original_ps1='theme> '; PROMPT=$original_ps1; KEEP=value
wolf activate foo || exit $?
# Simulate a theme rebuilding the prompt before zsh's precmd hooks run.
PROMPT=$original_ps1; _wolf_zsh_prompt
[[ "$$" = "$original_pid" && "$PWD" = "$original_pwd" && "$PATH" = "$original_path" && "$KEEP" = value && "$WOLF_ACTIVE_ENV" = foo && "$PROMPT" == *foo* ]] || exit 10
wolf activate bar || exit $?
PROMPT=$original_ps1; _wolf_zsh_prompt
[[ "$WOLF_ACTIVE_ENV" = bar && "$PROMPT" == *bar* && "$PROMPT" != *foo* ]] || exit 11
wolf info >/dev/null || exit $?
cd /; wolf run --plan >/dev/null || exit $?
wolf deactivate
[[ -z "${{WOLF_ACTIVE_ENV+x}}" && "$PROMPT" = "$original_ps1" && "$$" = "$original_pid" && "$KEEP" = value ]] || exit 12
'''
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

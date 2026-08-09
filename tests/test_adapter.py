import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
ADAPTER = ROOT / "prime-agent-multica"


class AdapterTests(unittest.TestCase):
    def run_with_fake_prime(self, args, session_dir):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-prime-agent"
            fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env.update(
                PRIME_AGENT_BIN=str(fake),
                PRIME_AGENT_SESSION_DIR=str(session_dir),
            )
            return subprocess.run(
                [str(ADAPTER), *args],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_translates_session_to_prime_canonical_directory(self):
        result = self.run_with_fake_prime(
            ["-p", "--mode", "json", "--session", "/tmp/multica/123.jsonl"],
            "/tmp/prime-sessions",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["-p", "--mode", "json", "--resume", "/tmp/prime-sessions/123.jsonl"],
        )


    def test_enables_worker_cleanup_frontend(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-prime-agent"
            fake.write_text("#!/bin/sh\nprintf '%s\n' \"$PRIME_AGENT_INTERNAL_LEGACY_OWNED_WORKER_FRONTEND\"\n")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env["PRIME_AGENT_BIN"] = str(fake)
            env.pop("PRIME_AGENT_INTERNAL_LEGACY_OWNED_WORKER_FRONTEND", None)
            result = subprocess.run(
                [str(ADAPTER), "--mode", "json"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "1")

    def test_retries_transient_active_session_race(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-prime-agent"
            marker = Path(tmp) / "failed-once"
            fake.write_text(
                "#!/bin/sh\n"
                f"if [ ! -f '{marker}' ]; then touch '{marker}'; "
                "echo 'Error: Session is already active in test-owner' >&2; exit 1; fi\n"
                "printf '%s\n' success\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env.update(
                PRIME_AGENT_BIN=str(fake),
                PRIME_AGENT_MULTICA_RETRY_ATTEMPTS="3",
                PRIME_AGENT_MULTICA_RETRY_DELAY="0.01",
            )
            result = subprocess.run(
                [str(ADAPTER), "--mode", "json"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "success")
        self.assertIn("Session is already active", result.stderr)

    def test_adds_noninteractive_json_defaults(self):
        result = self.run_with_fake_prime(["--provider", "test"], "/tmp/prime-sessions")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["-p", "--provider", "test", "--mode", "json"],
        )


if __name__ == "__main__":
    unittest.main()

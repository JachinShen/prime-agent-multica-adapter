import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
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

    def test_rpc_mode_is_transparent_and_does_not_inject_print(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-prime-agent"
            fake.write_text(
                "#!/bin/sh\n"
                "cat\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env["PRIME_AGENT_BIN"] = str(fake)
            result = subprocess.run(
                [str(ADAPTER), "--mode", "rpc", "--no-session"],
                cwd=ROOT,
                env=env,
                input='{"id":"models","type":"get_available_models"}\n',
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '{"id":"models","type":"get_available_models"}\n')

    def test_retries_replay_the_prompt_from_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-prime-agent"
            marker = Path(tmp) / "failed-once"
            attempts = Path(tmp) / "attempts"
            fake.write_text(
                "#!/bin/sh\n"
                f"cat >> '{attempts}'\n"
                f"if [ ! -f '{marker}' ]; then touch '{marker}'; "
                "echo 'Session is already active in test-owner' >&2; exit 1; fi\n"
                "printf '%s\n' success\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env.update(
                PRIME_AGENT_BIN=str(fake),
                PRIME_AGENT_MULTICA_RETRY_ATTEMPTS="2",
                PRIME_AGENT_MULTICA_RETRY_DELAY="0.01",
            )
            result = subprocess.run(
                [str(ADAPTER), "--mode", "json"],
                cwd=ROOT,
                env=env,
                input="replayed prompt\n",
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(attempts.read_text(), "replayed prompt\nreplayed prompt\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "success")

    @unittest.skipUnless(os.name == "posix", "process-group semantics are POSIX-specific")
    def test_cancellation_force_kills_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake = tmp_path / "fake-prime-agent"
            child_pid = tmp_path / "child.pid"
            fake.write_text(
                f"#!{sys.executable}\n"
                "import os, signal, subprocess, time\n"
                f"child = subprocess.Popen([{sys.executable!r}, '-c', "
                "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])\n"
                f"open({str(child_pid)!r}, 'w').write(str(child.pid))\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
                "while True: time.sleep(1)\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env.update(
                PRIME_AGENT_BIN=str(fake),
                PRIME_AGENT_MULTICA_SHUTDOWN_TIMEOUT="0.1",
            )
            adapter = subprocess.Popen(
                [str(ADAPTER), "--mode", "json"],
                cwd=ROOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert adapter.stdin is not None
            adapter.stdin.close()
            deadline = time.monotonic() + 2
            while not child_pid.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(child_pid.exists(), "fake Prime Agent did not start its descendant")
            descendant_pid = int(child_pid.read_text())
            started = time.monotonic()
            adapter.send_signal(signal.SIGTERM)
            _, stderr = adapter.communicate(timeout=4)
            self.assertEqual(adapter.returncode, 143, stderr)
            self.assertLess(time.monotonic() - started, 3)
            gone_deadline = time.monotonic() + 2
            while time.monotonic() < gone_deadline:
                try:
                    os.kill(descendant_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                self.fail("cancelled turn left a descendant process alive")

    def test_cancellation_interrupts_bounded_retry_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-prime-agent"
            fake.write_text(
                "#!/bin/sh\n"
                "echo 'Session is already active in live-owner' >&2\n"
                "exit 1\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env.update(
                PRIME_AGENT_BIN=str(fake),
                PRIME_AGENT_MULTICA_RETRY_ATTEMPTS="20",
                PRIME_AGENT_MULTICA_RETRY_DELAY="10",
                PRIME_AGENT_MULTICA_RETRY_WINDOW="60",
                PRIME_AGENT_MULTICA_SHUTDOWN_TIMEOUT="0.1",
            )
            adapter = subprocess.Popen(
                [str(ADAPTER), "--mode", "json"],
                cwd=ROOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            assert adapter.stdin is not None
            adapter.stdin.close()
            time.sleep(0.2)
            started = time.monotonic()
            adapter.send_signal(signal.SIGTERM)
            _, stderr = adapter.communicate(timeout=3)
            self.assertEqual(adapter.returncode, 143, stderr)
            self.assertLess(time.monotonic() - started, 2)

    def test_live_owner_is_not_killed_and_retry_eventually_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            try:
                fake = tmp_path / "fake-prime-agent"
                attempts = tmp_path / "attempts"
                fake.write_text(
                    "#!/bin/sh\n"
                    f"n=$(cat {str(attempts)!r} 2>/dev/null || echo 0)\n"
                    "n=$((n + 1)); printf '%s' \"$n\" > " + repr(str(attempts)) + "\n"
                    "if kill -0 \"$HOLDER_PID\" 2>/dev/null; then\n"
                    "  echo 'Session is already active in live-owner' >&2; exit 1\n"
                    "fi\n"
                    "exit 0\n"
                )
                fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
                env = os.environ.copy()
                env.update(
                    PRIME_AGENT_BIN=str(fake),
                    HOLDER_PID=str(holder.pid),
                    PRIME_AGENT_MULTICA_RETRY_ATTEMPTS="3",
                    PRIME_AGENT_MULTICA_RETRY_DELAY="0.01",
                    PRIME_AGENT_MULTICA_RETRY_WINDOW="1",
                )
                result = subprocess.run(
                    [str(ADAPTER), "--mode", "json"],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(attempts.read_text(), "3")
                self.assertIsNone(holder.poll(), "adapter must not reclaim a live owner")
            finally:
                holder.terminate()
                holder.wait(timeout=2)

    def test_model_rows_are_normalized_and_diagnostics_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "fake-prime-agent"
            fake.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = model ]; then\n"
                "  printf '%s\n' 'provider model context' 'openai:gpt-5.5' 'opencode-go  glm-5.2  1M' 'Warning: No models match pattern x'\n"
                "fi\n"
            )
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env["PRIME_AGENT_BIN"] = str(fake)
            result = subprocess.run(
                [str(ADAPTER), "--list-models"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["openai gpt-5.5", "opencode-go glm-5.2"])


if __name__ == "__main__":
    unittest.main()

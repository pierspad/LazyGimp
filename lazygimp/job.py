from __future__ import annotations

from .util import clean_output_line
from typing import Optional
import os
import pty
import queue
import select
import signal
import shutil
import subprocess
import threading
import urllib.request

# ---------------------------------------------------------------------------
# Job — background work + logging, shared by every long-running action
# (installs, downloads, removals) whether driven by the GUI or the CLI.
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, log_queue: Optional["queue.Queue[str]"] = None, password_prompt=None):
        self.log_queue = log_queue
        self.password_prompt = password_prompt  # callable(str) -> str, GUI-only
        self.cancel_event = threading.Event()
        self.proc: Optional[subprocess.Popen] = None

    def cancel(self):
        self.cancel_event.set()
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def log(self, msg: str):
        print(msg, flush=True)
        if self.log_queue is not None:
            self.log_queue.put(msg)

    def run_cmd(self, cmd: list[str], *, log_as: Optional[list[str]] = None, **kw) -> int:
        # log_as lets a call site substitute a short, redacted description
        # for the echoed command line — needed for anything built with
        # `-c <inline script>`, where the real argv can run to several KB
        # and, worse, may contain secrets (e.g. an HF token interpolated
        # into the script text) that must never hit stdout/the GUI log.
        display = log_as if log_as is not None else cmd
        if self.cancel_event.is_set():
            self.log("Cancelled — skipping: " + " ".join(display))
            return -1
        self.log("$ " + " ".join(display))
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, **kw)
        for line in iter(self.proc.stdout.readline, ""):
            if line:
                clean = clean_output_line(line.rstrip("\n"))
                if clean:
                    self.log(clean)
        self.proc.wait()
        rc = self.proc.returncode
        self.proc = None
        return rc

    def run_cmd_capture(self, cmd: list[str], *, log_as: Optional[list[str]] = None, **kw) -> tuple[int, list[str]]:
        display = log_as if log_as is not None else cmd
        if self.cancel_event.is_set():
            self.log("Cancelled — skipping: " + " ".join(display))
            return -1, []
        self.log("$ " + " ".join(display))
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, **kw)
        lines: list[str] = []
        for line in iter(self.proc.stdout.readline, ""):
            if line:
                clean = clean_output_line(line.rstrip("\n"))
                if clean:
                    self.log(clean)
                    lines.append(clean)
        self.proc.wait()
        rc = self.proc.returncode
        self.proc = None
        return rc, lines

    def run_root(self, cmd: list[str], env: Optional[dict] = None) -> int:
        """Run a command that needs root. With a GUI password_prompt, uses a
        pty so an internal `sudo` can actually prompt (a plain subprocess has
        no controlling terminal at all). From a real terminal (CLI usage),
        sudo already has one — no pty tricks needed, just run it directly."""
        env = env or os.environ.copy()
        if os.geteuid() == 0:
            return self.run_cmd(cmd, env=env)
        prefix = ["sudo"] if shutil.which("sudo") else (["doas"] if shutil.which("doas") else None)
        if prefix is None:
            self.log("ERROR: root privileges required, but neither sudo nor doas is installed.")
            return 1
        full_cmd = prefix + cmd
        if self.password_prompt is not None:
            return run_cmd_sudo_pty(self, full_cmd, env, self.password_prompt)
        self.log("$ " + " ".join(full_cmd) + "  (may prompt for your password below)")
        try:
            r = subprocess.run(full_cmd, env=env)
            return r.returncode
        except Exception as e:
            self.log(f"ERROR: {e}")
            return 1

    def download(self, url: str, dest: str, cancel_event: Optional[threading.Event] = None, progress_cb=None,
                 headers: Optional[dict] = None) -> bool:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part = dest + ".part"
        self.log(f"Downloading {url}")
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as resp, open(part, "wb") as out:
                total = int(resp.headers.get("Content-Length", 0))
                read = 0
                last_pct = -1
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        self.log("Cancelled.")
                        return False
                    buf = resp.read(1024 * 256)
                    if not buf:
                        break
                    out.write(buf)
                    read += len(buf)
                    if progress_cb:
                        progress_cb(read, total)
                    if total:
                        pct = int(read * 100 / total)
                        if pct != last_pct and pct % 5 == 0:
                            self.log(f"  {pct}%  ({read // (1024*1024)} MB / {total // (1024*1024)} MB)")
                            last_pct = pct
            os.replace(part, dest)
            self.log(f"Saved to {dest}")
            return True
        except Exception as e:
            self.log(f"ERROR downloading {url}: {e}")
            return False
        finally:
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass

def run_cmd_sudo_pty(job: Job, cmd: list[str], env: dict, password_prompt) -> int:
    """Run `cmd` with its controlling terminal attached to a fresh pty, so an
    internal `sudo` can prompt for a password even though this process (a Tk
    GUI) has none of its own. `password_prompt(text) -> str` must block until
    answered; it is responsible for hopping onto the GUI's own main thread
    and back, if needed."""
    job.log("$ " + " ".join(cmd))
    pid, master_fd = pty.fork()
    if pid == 0:  # child
        try:
            os.execvpe(cmd[0], cmd, env)
        except Exception:
            os._exit(127)

    buf = b""
    try:
        while True:
            if job.cancel_event.is_set():
                job.log("Cancel requested — terminating...")
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                r, _, _ = select.select([master_fd], [], [], 0.2)
            except OSError:
                break
            if master_fd in r:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    chunk = b""
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    clean = clean_output_line(line.decode(errors="replace").rstrip("\r"))
                    if clean:
                        job.log(clean)
                tail = buf.decode(errors="replace")
                if tail and tail.rstrip().endswith(":") and "password" in tail.lower():
                    pw = password_prompt(tail.strip())
                    os.write(master_fd, ((pw or "") + "\n").encode())
                    buf = b""
            try:
                wpid, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                break
            if wpid == pid:
                try:
                    while True:
                        chunk = os.read(master_fd, 4096)
                        if not chunk:
                            break
                        buf += chunk
                except OSError:
                    pass
                if buf:
                    clean = clean_output_line(buf.decode(errors="replace"))
                    if clean:
                        job.log(clean)
                    buf = b""
                return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
    finally:
        if buf:
            clean = clean_output_line(buf.decode(errors="replace"))
            if clean:
                job.log(clean)
        try:
            os.close(master_fd)
        except OSError:
            pass
    try:
        _, status = os.waitpid(pid, 0)
        return os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
    except ChildProcessError:
        return 1


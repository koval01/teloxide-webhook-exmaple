#!/usr/bin/env python3
import subprocess
import re
import time
import signal
import sys
import os
from threading import Event

LOCAL_URL = "http://localhost:8005"
TIMEOUT = 60
LOGFILE = "/tmp/cloudflared_log_py"

class TunnelManager:
  def __init__(self):
    self.cloudflared_process = None
    self.cargo_process = None
    self.app_process = None
    self.shutdown_event = Event()

  def cleanup(self):
    """Graceful cleanup of processes"""
    print("\nTerminating processes...")

    if self.app_process and self.app_process.poll() is None:
      print("Stopping the application...")
      self.app_process.terminate()
      try:
        self.app_process.wait(timeout=5)
      except subprocess.TimeoutExpired:
        self.app_process.kill()

    if self.cargo_process and self.cargo_process.poll() is None:
      print("Stopping cargo...")
      self.cargo_process.terminate()
      try:
        self.cargo_process.wait(timeout=5)
      except subprocess.TimeoutExpired:
        self.cargo_process.kill()

    if self.cloudflared_process and self.cloudflared_process.poll() is None:
      print("Stopping cloudflared...")
      self.cloudflared_process.terminate()
      try:
        self.cloudflared_process.wait(timeout=3)
      except subprocess.TimeoutExpired:
        self.cloudflared_process.kill()

    if os.path.exists(LOGFILE):
      os.remove(LOGFILE)

  def signal_handler(self, sig, frame):
    """Termination signal handler"""
    print(f"\nReceived signal {sig}, terminating...")
    self.shutdown_event.set()
    self.cleanup()
    sys.exit(0)

  def run_cloudflared(self):
    """Launch cloudflared and return the public URL"""
    print(f"Starting cloudflared --url {LOCAL_URL} (log -> {LOGFILE})")

    with open(LOGFILE, 'w') as log_file:
      self.cloudflared_process = subprocess.Popen(
        ['cloudflared', '--url', LOCAL_URL],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True
      )

    print(f"Waiting for public URL (timeout {TIMEOUT}s)...")

    start_time = time.time()
    public_url = None

    while time.time() - start_time < TIMEOUT and not self.shutdown_event.is_set():
      try:
        with open(LOGFILE, 'r') as f:
          content = f.read()
          match = re.search(r'https://[A-Za-z0-9._-]+\.trycloudflare\.com', content)
          if match:
            public_url = match.group(0)
            break
      except FileNotFoundError:
        pass

      time.sleep(10)

    if not public_url:
      raise Exception(f"Failed to get public URL from cloudflared logs within {TIMEOUT}s")

    host = public_url.replace('https://', '').rstrip('/')

    print(f"PUBLIC_URL = {public_url}")
    print(f"HOST       = {host}")

    os.environ['PUBLIC_URL'] = public_url
    os.environ['HOST'] = host

    return public_url, host

  def run_cargo_build(self):
    """Run cargo build"""
    print("Running cargo build...")

    build_process = subprocess.run([
      'cargo', 'build',
      '--color=always',
      '--package', 'teloxidebot',
      '--bin', 'teloxidebot',
      '--profile', 'dev'
    ], capture_output=False)

    if build_process.returncode == 0:
      print("Build completed successfully!")
      return True
    else:
      print(f"Build failed (code: {build_process.returncode})")
      return False

  def run_application(self):
    """Run the built application"""
    print("Starting application...")

    self.app_process = subprocess.Popen([
      'cargo', 'run',
      '--color=always',
      '--package', 'teloxidebot',
      '--bin', 'teloxidebot',
      '--profile', 'dev'
    ])

    return self.app_process

  def wait_for_interrupt(self):
    """Wait for user interrupt signal"""
    print("\n" + "="*50)
    print("All processes are running. Press Ctrl+C to stop.")
    print("="*50)

    try:
      while not self.shutdown_event.is_set():
        time.sleep(1)

        if self.cloudflared_process and self.cloudflared_process.poll() is not None:
          print("cloudflared exited unexpectedly!")
          break

        if self.app_process and self.app_process.poll() is not None:
          print("Application exited unexpectedly!")
          break

    except KeyboardInterrupt:
      print("\nCtrl+C received, terminating...")
      self.shutdown_event.set()

def main():
  manager = TunnelManager()

  signal.signal(signal.SIGINT, manager.signal_handler)
  signal.signal(signal.SIGTERM, manager.signal_handler)

  try:
    public_url, host = manager.run_cloudflared()

    build_success = manager.run_cargo_build()

    if build_success:
      app_process = manager.run_application()
      print(f"Application started (PID: {app_process.pid})")

      manager.wait_for_interrupt()
    else:
      print("Build failed, terminating...")
      sys.exit(1)

  except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    manager.cleanup()
    sys.exit(1)

  finally:
    manager.cleanup()

if __name__ == "__main__":
  main()

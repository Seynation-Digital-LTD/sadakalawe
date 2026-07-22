#!/usr/bin/env python3
"""
Sadakalawe Sales System — Launcher
Run directly:  python launcher.py
Or double-click Sadakalawe.app (built by build_app.sh)
"""
import sys
import os
import threading
import time
import webbrowser
import socket
import logging

# ── Path setup ────────────────────────────────────────────────────
# Works both from the project directory and from inside a py2app bundle.
if getattr(sys, 'frozen', False):
    # Inside a py2app bundle — Resources/ holds the project files
    PROJECT_DIR = os.path.normpath(
        os.path.join(os.path.dirname(sys.executable), '..', 'Resources'))
else:
    PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, PROJECT_DIR)
os.chdir(PROJECT_DIR)

from config import PORT          # single source of truth — see config.py
LOG_FILE = os.path.join(PROJECT_DIR, 'sadakalawe.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger('launcher')


# ── Helpers ───────────────────────────────────────────────────────

def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def is_sadakalawe(port: int) -> bool:
    """Confirm the app answering on `port` is ours and not some other project."""
    import urllib.request
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/login', timeout=2) as r:
            return b'Sadakalawe' in r.read(20000)
    except Exception:
        return False


def wait_for_server(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_in_use(port):
            return True
        time.sleep(0.25)
    return False


def notify(title: str, message: str) -> None:
    """macOS notification — silently ignored if osascript unavailable."""
    try:
        os.system(
            f"osascript -e 'display notification \"{message}\" with title \"{title}\"'"
        )
    except Exception:
        pass


def alert(message: str) -> None:
    """macOS dialog box for critical errors."""
    try:
        os.system(
            f"osascript -e 'tell app \"System Events\" to display dialog \"{message}\" "
            f"buttons {{\"OK\"}} default button \"OK\" with icon caution'"
        )
    except Exception:
        pass


# ── Main ──────────────────────────────────────────────────────────

def main() -> None:
    log.info('=' * 60)
    log.info('Sadakalawe Sales System starting …')
    log.info('Project directory: %s', PROJECT_DIR)

    # If the port is busy, make sure it is actually Sadakalawe before opening a
    # tab — otherwise we'd hand the user someone else's app and call it ours.
    if port_in_use(PORT):
        if is_sadakalawe(PORT):
            log.info('Server already running on :%d — opening browser tab', PORT)
            webbrowser.open(f'http://127.0.0.1:{PORT}/')
        else:
            msg = (f'Port {PORT} is being used by another program, so Sadakalawe '
                   f'cannot start.\n\nClose whatever is using port {PORT} and try '
                   f'again, or set a different port with PORT=… in the environment.')
            log.error(msg)
            alert(msg)
        return

    # Build and start Flask
    try:
        from app import create_app
        flask_app = create_app()
    except Exception as exc:
        msg = f'Could not start Sadakalawe:\n{exc}'
        log.exception(msg)
        alert(msg)
        sys.exit(1)

    def run_server() -> None:
        try:
            flask_app.run(
                host='127.0.0.1',
                port=PORT,
                debug=False,
                use_reloader=False,
                threaded=True,
            )
        except Exception as exc:
            log.exception('Server crashed: %s', exc)

    server_thread = threading.Thread(target=run_server, name='flask', daemon=True)
    server_thread.start()

    log.info('Waiting for server on :%d …', PORT)
    if wait_for_server(PORT, timeout=20):
        log.info('Server ready — opening browser')
        notify('Sadakalawe', 'System is ready ✓  →  http://localhost:%d' % PORT)
        webbrowser.open(f'http://127.0.0.1:{PORT}/')
    else:
        msg = (
            'Sadakalawe server did not start within 20 seconds.\n'
            f'Check the log file:\n{LOG_FILE}'
        )
        log.error(msg)
        alert(msg)
        sys.exit(1)

    # Block main thread — daemon server thread keeps running
    server_thread.join()


if __name__ == '__main__':
    main()

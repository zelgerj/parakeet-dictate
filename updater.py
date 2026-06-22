"""
updater.py — self-update for the notarized Parakeet Dictate .app.

Checks the GitHub Releases API for a newer version, downloads the notarized DMG,
verifies its Developer-ID signature + notarization OFFLINE (no trust in the network),
then atomically swaps the app in /Applications and relaunches — with rollback.

The only routine outbound call the app makes; GitHub-only, opt-out-able.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlparse

OWNER_REPO = "zelgerj/parakeet-dictate"
API_LATEST = "https://api.github.com/repos/%s/releases/latest" % OWNER_REPO
DMG_NAME = "ParakeetDictate.dmg"
APP_NAME = "Parakeet Dictate.app"
BUNDLE_ID = "digital.zelger.parakeetdictate"
TEAM_ID = "CS72WV49JK"
# Hard-pinned Designated Requirement: this exact bundle id, signed by Apple, by THIS team.
_DR = ('identifier "%s" and anchor apple generic and '
       'certificate leaf[subject.OU] = "%s"' % (BUNDLE_ID, TEAM_ID))


def _ver(s):
    nums = []
    for part in (s or "").strip().lstrip("vV").split("."):
        d = ""
        for ch in part:
            if ch.isdigit():
                d += ch
            else:
                break
        nums.append(int(d) if d else 0)
    return tuple(nums) or (0,)


def is_newer(remote, local):
    return _ver(remote) > _ver(local)


def _host_ok(url):
    try:
        u = urlparse(url)
    except Exception:
        return False
    h = u.hostname or ""
    return u.scheme == "https" and (h == "github.com" or h.endswith(".githubusercontent.com"))


def check(current_version, etag=None, timeout=10):
    """Return (info, new_etag). `info` is dict(version, dmg_url, notes) if a strictly
    newer release exists, else None. Fails silent (returns (None, etag)) on ANY error
    (offline, rate-limited, 304-not-modified, parse error)."""
    req = urllib.request.Request(API_LATEST, headers={
        "User-Agent": "ParakeetDictate/%s (+https://github.com/%s)" % (current_version, OWNER_REPO),
        "Accept": "application/vnd.github+json",
    })
    if etag:
        req.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            new_etag = r.headers.get("ETag") or etag
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return (None, etag)
    tag = (data.get("tag_name") or "").lstrip("vV")
    if not tag or not is_newer(tag, current_version):
        return (None, new_etag)
    dmg_url = None
    for a in data.get("assets") or []:
        if a.get("name") == DMG_NAME:
            dmg_url = a.get("browser_download_url")
            break
    if not dmg_url or not _host_ok(dmg_url):
        return (None, new_etag)
    return ({"version": tag, "dmg_url": dmg_url, "notes": data.get("body") or ""}, new_etag)


def _ok(cmd):
    try:
        return subprocess.run(cmd, capture_output=True).returncode == 0
    except Exception:
        return False


def verify(app_path):
    """All gates must pass on the EXACT bytes we'd run: structural integrity,
    the Developer-ID identity pin, and notarization (offline via the stapled ticket)."""
    return (
        _ok(["codesign", "--verify", "--deep", "--strict", app_path])
        and _ok(["codesign", "--verify", "-R", "=" + _DR, app_path])
        and _ok(["spctl", "-a", "-t", "exec", app_path])
    )


def current_app_path():
    p = sys.executable
    while p and p != "/" and not p.endswith(".app"):
        p = os.path.dirname(p)
    return p if p.endswith(".app") else None


def _rmrf(p):
    subprocess.run(["rm", "-rf", p], capture_output=True)


def _download(url, dest, progress=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "ParakeetDictate"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if progress:
                progress(got, total)


def install(dmg_url, progress=None):
    """Download → verify → atomic swap → relaunch. Returns (status, message):
      'relaunching' -> verified + swapped; this call then spawns a relaunch helper and
                       os._exit()s, so it does not return in that case.
      'manual'      -> /Applications not writable; opened the DMG for manual drag-install.
      'error'       -> message says why; nothing on disk was changed.
    """
    target = current_app_path()
    if not target:
        return ("error", "Couldn't locate the installed app (is it in /Applications?).")
    apps_dir = os.path.dirname(target)

    tmp = tempfile.mkdtemp(prefix="parakeet-update-")
    dmg = os.path.join(tmp, DMG_NAME)
    mount = os.path.join(tmp, "mnt")
    try:
        _download(dmg_url, dmg, progress)
    except Exception as e:
        _rmrf(tmp)
        return ("error", "Download failed: %s" % e)

    if not os.access(apps_dir, os.W_OK):
        subprocess.Popen(["open", dmg])
        return ("manual", "Couldn't update in place — opened the installer; drag it into Applications.")

    os.makedirs(mount, exist_ok=True)
    if not _ok(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", mount, dmg]):
        _rmrf(tmp)
        return ("error", "Couldn't open the downloaded update.")
    staged = target + ".new"
    try:
        _rmrf(staged)
        if not _ok(["ditto", os.path.join(mount, APP_NAME), staged]):
            return ("error", "Couldn't extract the update.")
    finally:
        if not _ok(["hdiutil", "detach", mount, "-quiet"]):
            subprocess.run(["hdiutil", "detach", mount, "-force"], capture_output=True)

    # MANDATORY authenticity gate. Reject anything not signed+notarized by our Team ID.
    if not verify(staged):
        _rmrf(staged)
        _rmrf(tmp)
        return ("error", "The update failed its signature/notarization check — not installed.")

    old = target + ".old"
    try:
        _rmrf(old)
        os.rename(target, old)      # move the live app aside (atomic, same volume)
        os.rename(staged, target)   # move the verified app into place
    except Exception as e:
        if not os.path.exists(target) and os.path.exists(old):
            try:
                os.rename(old, target)
            except Exception:
                pass
        _rmrf(staged)
        _rmrf(tmp)
        return ("error", "Couldn't swap the app: %s" % e)

    _spawn_relaunch_helper(target, old)
    _rmrf(tmp)
    os._exit(0)


def _spawn_relaunch_helper(app_path, old_backup):
    """Detached helper: wait for us to quit, relaunch the new app, and roll back from
    the backup if it doesn't come up."""
    script = (
        '#!/bin/sh\n'
        'APP="%s"\nOLD="%s"\nPID=%d\n'
        'while kill -0 "$PID" 2>/dev/null; do sleep 0.3; done\n'
        'open -n "$APP"\n'
        'sleep 7\n'
        'if pgrep -f "$APP/Contents/MacOS/" >/dev/null 2>&1; then\n'
        '  rm -rf "$OLD"\n'
        'else\n'
        '  rm -rf "$APP.failed"; mv "$APP" "$APP.failed" 2>/dev/null\n'
        '  mv "$OLD" "$APP" 2>/dev/null\n'
        '  open -n "$APP"\n'
        'fi\n'
    ) % (app_path, old_backup, os.getpid())
    f = tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False)
    f.write(script)
    f.close()
    subprocess.Popen(["/bin/sh", f.name], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cleanup_old(app_path):
    """On a healthy launch, remove any leftover backups from a previous update."""
    if not app_path:
        return
    for suffix in (".old", ".failed", ".new"):
        _rmrf(app_path + suffix)

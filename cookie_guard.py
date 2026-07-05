#!/usr/bin/env python3
r"""
COOKIE GUARD  —  all-in-one, single-file cookie defense for Brave/Chrome on Windows.

Everything is in THIS ONE FILE. No other scripts needed.

It runs three things together in the background:
  1. EXTENSION WATCH  - names the exact extension that calls a cookie API
                        (needs Brave started with --enable-extension-activity-logging;
                         see setup note it prints if the log is off).
  2. FILE WATCH       - names the exact external program that opens your cookie file
                        (Windows Restart Manager; no admin needed).
  3. HOURLY AUDIT     - alerts if a NEW cookie-capable extension appears.

All alerts print here, pop a desktop notification, and are saved to cookie_guard.log.

COMMANDS
  python cookie_guard.py --browser brave                 # run everything (default)
  python cookie_guard.py --browser brave --audit         # just list risky extensions and exit
  python cookie_guard.py --browser brave --save-baseline # remember current extensions as trusted
  python cookie_guard.py --browser brave --include-webrequest  # also flag webRequest.* (noisier)
Stop: Ctrl+C   (if launched hidden, end 'pythonw.exe' in Task Manager)
"""
import os
import sys
import json
import time
import shutil
import sqlite3
import tempfile
import argparse
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

try:
    from plyer import notification as _notif
except Exception:  # noqa: BLE001
    _notif = None

IS_WIN = sys.platform.startswith("win")
EPOCH_DIFF = 11644473600  # seconds between 1601 and 1970 epochs

# ===========================================================================
# Config / paths
# ===========================================================================
BROWSERS = {
    "brave": {"sub": ("BraveSoftware", "Brave-Browser"), "binary": "brave.exe",
              "app": ("BraveSoftware", "Brave-Browser", "Application"),
              "linux": "BraveSoftware/Brave-Browser"},
    "chrome": {"sub": ("Google", "Chrome"), "binary": "chrome.exe",
               "app": ("Google", "Chrome", "Application"),
               "linux": "google-chrome"},
}


def user_data_dir(browser):
    home = Path.home()
    spec = BROWSERS[browser]
    if IS_WIN:
        base = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        return base.joinpath(*spec["sub"], "User Data")
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / spec["sub"][0] / spec["sub"][1]
    return home / ".config" / spec["linux"]


def detect_browser():
    for name in ("brave", "chrome"):
        if user_data_dir(name).exists():
            return name
    return "brave"


def find_profiles(udd):
    if not udd.exists():
        return []
    return [e for e in udd.iterdir()
            if e.is_dir() and (e.name == "Default" or e.name.startswith("Profile "))]


def sensitive_files(browser):
    udd = user_data_dir(browser)
    files = []
    for prof in find_profiles(udd):
        for c in (prof / "Network" / "Cookies", prof / "Cookies"):
            if c.exists():
                files.append(c)
    ls = udd / "Local State"
    if ls.exists():
        files.append(ls)
    return files


def legit_exes(browser):
    if not IS_WIN:
        return set()
    spec = BROWSERS[browser]
    cands = [user_data_dir(browser).parent / "Application" / spec["binary"]]
    for root in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                 os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                 os.environ.get("LOCALAPPDATA", "")):
        if root:
            cands.append(Path(root).joinpath(*spec["app"], spec["binary"]))
    return {str(c).lower() for c in cands if c.exists()}


def find_activity_dbs(browser):
    out = []
    for prof in find_profiles(user_data_dir(browser)):
        db = prof / "Extension Activity"
        if db.exists():
            out.append((prof, db))
    return out


def ext_name(profile, ext_id):
    ext_root = profile / "Extensions" / ext_id
    if not ext_root.exists():
        return ext_id
    versions = [d for d in ext_root.iterdir() if d.is_dir()]
    if not versions:
        return ext_id
    vdir = max(versions, key=lambda d: d.name)
    mp = vdir / "manifest.json"
    if not mp.exists():
        return ext_id
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return ext_id
    name = m.get("name", ext_id)
    if name.startswith("__MSG_"):
        inner = name[len("__MSG_"):]
        key = inner[:-2] if inner.endswith("__") else inner
        for loc in (m.get("default_locale", "en"), "en", "en_US"):
            lp = vdir / "_locales" / loc / "messages.json"
            if lp.exists():
                try:
                    msgs = json.loads(lp.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    continue
                for k, v in msgs.items():
                    if k.lower() == key.lower():
                        return v.get("message", name)
    return name


# ===========================================================================
# Shared alerting
# ===========================================================================
LOG = Path(__file__).resolve().with_name("cookie_guard.log")
_log_lock = threading.Lock()
_notify_enabled = True
stop = threading.Event()


def log(line):
    with _log_lock:
        try:
            with LOG.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {line}\n")
        except OSError:
            pass


def notify(title, message):
    if _notify_enabled and _notif is not None:
        try:
            _notif.notify(title=title, message=message, timeout=10)
        except Exception:  # noqa: BLE001
            pass


def alert(header, lines, notify_title, notify_msg):
    block = "\n" + "!" * 70 + f"\n  {header}\n" + "!" * 70
    for lbl, val in lines:
        block += f"\n  {lbl:<10}: {val}"
    block += "\n" + "!" * 70
    print(block)
    log(f"{header} | " + " | ".join(f"{l}={v}" for l, v in lines))
    notify(notify_title, notify_msg)


# ===========================================================================
# 1) Extension activity watcher (which extension read a cookie)
# ===========================================================================
def _now_chrome_time():
    return int((time.time() + EPOCH_DIFF) * 1_000_000)


def _fmt_time(ct):
    try:
        return datetime.fromtimestamp(ct / 1_000_000 - EPOCH_DIFF).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return str(ct)


def _read_new_activity(db_path, since, patterns):
    tmp = Path(tempfile.gettempdir()) / "cg_activity_copy.db"
    try:
        shutil.copy2(db_path, tmp)
    except OSError:
        return [], since
    rows, newmax = [], since
    try:
        con = sqlite3.connect(str(tmp))
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        try:
            if "activitylog_full" in tables:
                like = " OR ".join(["api_name LIKE ?"] * len(patterns))
                q = (f"SELECT time, extension_id, api_name, args, page_url "
                     f"FROM activitylog_full WHERE ({like}) AND time > ? ORDER BY time")
                cur = con.execute(q, (*patterns, since))
            elif "activitylog_compressed" in tables and "string_ids" in tables:
                like = " OR ".join(["sa.value LIKE ?"] * len(patterns))
                q = (f"SELECT c.time AS time, se.value AS extension_id, sa.value AS api_name, "
                     f"sg.value AS args, su.value AS page_url FROM activitylog_compressed c "
                     f"LEFT JOIN string_ids se ON se.id=c.extension_id_x "
                     f"LEFT JOIN string_ids sa ON sa.id=c.api_name_x "
                     f"LEFT JOIN string_ids sg ON sg.id=c.args_x "
                     f"LEFT JOIN url_ids   su ON su.id=c.page_url_x "
                     f"WHERE ({like}) AND c.time > ? ORDER BY c.time")
                cur = con.execute(q, (*patterns, since))
            else:
                con.close()
                return [], since
            for r in cur.fetchall():
                rows.append(dict(r))
                if r["time"] and r["time"] > newmax:
                    newmax = r["time"]
        except sqlite3.OperationalError:
            pass
        con.close()
    except sqlite3.Error:
        return [], since
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return rows, newmax


def _cookie_names_from_args(args):
    """Pull the cookie name(s) out of an activity-log 'args' JSON string."""
    names = []
    try:
        data = json.loads(args)
        if isinstance(data, list):
            for it in data:
                if isinstance(it, dict) and it.get("name"):
                    names.append(str(it["name"]))
        elif isinstance(data, dict) and data.get("name"):
            names.append(str(data["name"]))
    except Exception:  # noqa: BLE001
        pass
    return names


def _is_bulk_call(api):
    """getAll / debugger calls can dump ALL cookies at once — always suspicious."""
    a = (api or "").lower()
    return a.endswith("getall") or a.startswith("debugger.")


def extension_watch_thread(browser, include_webrequest, burst_threshold, burst_window):
    dbs = find_activity_dbs(browser)
    if not dbs:
        msg = ("[EXT ] Extension activity log is OFF, so extension cookie-reads "
               "can't be seen yet.")
        print(msg)
        log(msg)
        print("       To enable: quit Brave, right-click its shortcut -> Properties,")
        print("       add  --enable-extension-activity-logging  to the Target box after a")
        print("       space, then launch Brave from that shortcut. Restart Cookie Guard.")
        return
    patterns = ["cookies.%", "debugger.%"] + (["webRequest.%"] if include_webrequest else [])
    print(f"[EXT ] watching {len(dbs)} activity log(s): cookies.*, debugger.*"
          + (", webRequest.*" if include_webrequest else ""))
    print(f"[EXT ] THEFT alert if an extension reads {burst_threshold}+ cookies within "
          f"{burst_window}s, or makes a bulk-dump call.")
    since = {str(db): _now_chrome_time() for _, db in dbs}
    seen = set()
    recent = {}       # ext_id -> deque[(wall_time, cookie_name)]
    last_theft = {}   # ext_id -> wall_time of last burst alert
    cooldown = max(5, burst_window)
    while not stop.is_set():
        for prof, db in dbs:
            rows, newmax = _read_new_activity(db, since[str(db)], patterns)
            since[str(db)] = newmax
            for r in rows:
                ext_id = r.get("extension_id") or "?"
                api = r.get("api_name") or "?"
                key = (ext_id, api, r.get("time"), (r.get("args") or "")[:60])
                if key in seen:
                    continue
                seen.add(key)
                name = ext_name(prof, ext_id)
                when = _fmt_time(r.get("time"))
                cnames = _cookie_names_from_args(r.get("args") or "")
                now = time.time()

                # 1) normal per-read alert (still pops every time)
                alert("EXTENSION READ A COOKIE",
                      [("extension", f"{name} ({ext_id})"),
                       ("api call", api),
                       ("cookie", ", ".join(cnames) if cnames else "(not shown)"),
                       ("time", when)],
                      "Extension read a cookie",
                      f"{name}: {api}")

                # 2) bulk-dump call = always a theft alert
                if _is_bulk_call(api):
                    alert("POSSIBLE COOKIE THEFT  (BULK-DUMP CALL)",
                          [("extension", f"{name} ({ext_id})"),
                           ("api call", api),
                           ("why", "getAll/debugger can read ALL cookies at once"),
                           ("time", when)],
                          "POSSIBLE COOKIE THEFT",
                          f"{name} made a bulk cookie-dump call ({api})")

                # 3) burst detection = many cookies read quickly
                dq = recent.setdefault(ext_id, deque())
                for item in (cnames or [api]):
                    dq.append((now, item))
                while dq and now - dq[0][0] > burst_window:
                    dq.popleft()
                if len(dq) >= burst_threshold and (now - last_theft.get(ext_id, 0)) > cooldown:
                    last_theft[ext_id] = now
                    distinct = list({n for _, n in dq})
                    alert("POSSIBLE COOKIE THEFT  (RAPID BURST)",
                          [("extension", f"{name} ({ext_id})"),
                           ("read", f"{len(dq)} cookies in <= {burst_window}s"),
                           ("cookies", ", ".join(distinct[:8])),
                           ("time", when)],
                          "POSSIBLE COOKIE THEFT",
                          f"{name} read {len(dq)} cookies quickly")
        stop.wait(1.5)


# ===========================================================================
# 2) File-access monitor (which external program opened the cookie file)
# ===========================================================================
def _win_rm_setup():
    import ctypes
    from ctypes import wintypes
    rstrtmgr = ctypes.WinDLL("rstrtmgr")
    kernel32 = ctypes.WinDLL("kernel32")
    RM_SESSION_KEY_LEN = 16
    CCH_RM_SESSION_KEY = RM_SESSION_KEY_LEN * 2
    CCH_RM_MAX_APP_NAME = 255
    CCH_RM_MAX_SVC_NAME = 63

    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [("dwProcessId", wintypes.DWORD),
                    ("ProcessStartTime", wintypes.FILETIME)]

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [("Process", RM_UNIQUE_PROCESS),
                    ("strAppName", wintypes.WCHAR * (CCH_RM_MAX_APP_NAME + 1)),
                    ("strServiceShortName", wintypes.WCHAR * (CCH_RM_MAX_SVC_NAME + 1)),
                    ("ApplicationType", ctypes.c_int),
                    ("AppStatus", wintypes.ULONG),
                    ("TSSessionId", wintypes.DWORD),
                    ("bRestartable", wintypes.BOOL)]

    def processes_using(path):
        session = wintypes.DWORD()
        key = (ctypes.c_wchar * (CCH_RM_SESSION_KEY + 1))()
        if rstrtmgr.RmStartSession(ctypes.byref(session), 0, key) != 0:
            return []
        try:
            resources = (ctypes.c_wchar_p * 1)(str(path))
            if rstrtmgr.RmRegisterResources(session, 1, resources, 0, None, 0, None) != 0:
                return []
            needed = wintypes.UINT(0)
            count = wintypes.UINT(0)
            reboot = wintypes.DWORD(0)
            rstrtmgr.RmGetList(session, ctypes.byref(needed), ctypes.byref(count),
                               None, ctypes.byref(reboot))
            n = needed.value
            if n == 0:
                return []
            arr = (RM_PROCESS_INFO * n)()
            count = wintypes.UINT(n)
            if rstrtmgr.RmGetList(session, ctypes.byref(needed), ctypes.byref(count),
                                  arr, ctypes.byref(reboot)) != 0:
                return []
            return [(arr[i].Process.dwProcessId, arr[i].strAppName) for i in range(count.value)]
        finally:
            rstrtmgr.RmEndSession(session)

    def exe_of(pid):
        h = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            size = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
            return None
        finally:
            kernel32.CloseHandle(h)

    return processes_using, exe_of


def file_watch_thread(browser):
    files = sensitive_files(browser)
    if not files:
        print("[FILE] no cookie files found; file watch not started.")
        return
    if not IS_WIN:
        print("[FILE] file watch (Restart Manager) is Windows-only; skipped.")
        return
    try:
        processes_using, exe_of = _win_rm_setup()
    except Exception as e:  # noqa: BLE001
        print(f"[FILE] could not init Windows Restart Manager: {e}")
        return
    trusted = legit_exes(browser)
    print(f"[FILE] watching {len(files)} cookie file(s); trusting {len(trusted)} browser binary path(s).")
    seen = set()
    while not stop.is_set():
        for f in files:
            for pid, app in processes_using(f):
                if pid == os.getpid():
                    continue
                exe = (exe_of(pid) or "").lower()
                if exe and exe in trusted:
                    continue
                key = (pid, str(f).lower())
                if key in seen:
                    continue
                seen.add(key)
                alert("EXTERNAL PROGRAM OPENED YOUR COOKIE FILE",
                      [("pid", pid), ("program", app or "?"),
                       ("exe", exe or "?"), ("file", f.name), ("path", str(f))],
                      "Program opened your cookie file",
                      f"{app or exe or 'A program'} opened {f.name}")
        stop.wait(0.7)


# ===========================================================================
# 3) Extension audit + hourly diff
# ===========================================================================
RISKY_PERMISSIONS = {
    "debugger": ("CRITICAL", "DevTools protocol can dump ALL cookies"),
    "cookies": ("HIGH", "Direct read/write of cookies"),
    "nativeMessaging": ("HIGH", "Can pipe data to a local companion program"),
    "proxy": ("MEDIUM", "Can route traffic through a proxy"),
    "webRequest": ("MEDIUM", "Can observe headers incl. Set-Cookie"),
    "webRequestBlocking": ("MEDIUM", "Can intercept requests"),
    "management": ("MEDIUM", "Can enumerate/disable other extensions"),
    "declarativeNetRequest": ("LOW", "Can act on network requests"),
    "tabs": ("LOW", "Can read tab URLs/titles"),
    "history": ("LOW", "Can read browsing history"),
    "browsingData": ("LOW", "Can clear browsing data"),
}
BROAD_HOSTS = {"<all_urls>", "*://*/*", "http://*/*", "https://*/*", "*://*/"}
SEV = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
BASELINE = Path(__file__).resolve().with_name("cookie_baseline.json")


def _is_host(p):
    return p == "<all_urls>" or "://" in p


def audit_all(browser):
    findings = []
    for prof in find_profiles(user_data_dir(browser)):
        ext_root = prof / "Extensions"
        if not ext_root.exists():
            continue
        for ext_dir in ext_root.iterdir():
            if not ext_dir.is_dir():
                continue
            vers = [d for d in ext_dir.iterdir() if d.is_dir()]
            if not vers:
                continue
            vdir = max(vers, key=lambda d: d.name)
            mp = vdir / "manifest.json"
            if not mp.exists():
                continue
            try:
                m = json.loads(mp.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            perms = []
            for fld in ("permissions", "optional_permissions", "host_permissions",
                        "optional_host_permissions"):
                perms += m.get(fld, [])
            api = [p for p in perms if not _is_host(p)]
            broad = sorted(set(p for p in perms if _is_host(p)) & BROAD_HOSTS)
            flags, mx = [], "NONE"
            for p in api:
                if p in RISKY_PERMISSIONS:
                    s, why = RISKY_PERMISSIONS[p]
                    flags.append((s, p, why))
                    mx = s if SEV[s] > SEV[mx] else mx
            if broad:
                s = "HIGH" if any(f[1] in ("cookies", "webRequest", "debugger") for f in flags) else "MEDIUM"
                flags.append((s, ", ".join(broad), "Broad host access"))
                mx = s if SEV[s] > SEV[mx] else mx
            if flags:
                findings.append({"id": ext_dir.name, "name": ext_name(prof, ext_dir.name),
                                 "profile": prof.name, "risk": mx,
                                 "flags": sorted(flags, key=lambda x: -SEV[x[0]])})
    findings.sort(key=lambda f: -SEV[f["risk"]])
    return findings


def print_audit(browser):
    findings = audit_all(browser)
    if not findings:
        print("No extensions with cookie-relevant permissions found.")
        return
    print(f"\n{'='*70}\n  {len(findings)} extension(s) can touch sensitive data\n{'='*70}")
    for f in findings:
        print(f"\n[{f['risk']}]  {f['name']}\n        id={f['id']}  profile={f['profile']}")
        for s, p, why in f["flags"]:
            print(f"          - ({s}) {p}: {why}")
    print(f"\nRemove anything you don't recognize at brave://extensions .\n")


def save_baseline(browser):
    data = {f["id"] + "@" + f["profile"]: {"name": f["name"], "risk": f["risk"]}
            for f in audit_all(browser)}
    BASELINE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Baseline saved: {len(data)} cookie-capable extension(s) -> {BASELINE.name}")


def diff_thread(browser, interval=3600):
    if stop.wait(15):
        return
    while not stop.is_set():
        if BASELINE.exists():
            try:
                base = json.loads(BASELINE.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                base = {}
            current = {f["id"] + "@" + f["profile"]: f for f in audit_all(browser)}
            added = [k for k in current if k not in base]
            for k in added:
                f = current[k]
                alert("NEW COOKIE-CAPABLE EXTENSION APPEARED",
                      [("extension", f"{f['name']} ({f['id']})"),
                       ("risk", f["risk"]), ("profile", f["profile"])],
                      "New cookie-capable extension",
                      f"{f['name']} ({f['risk']})")
        stop.wait(interval)


# ===========================================================================
# Main
# ===========================================================================
def main():
    global _notify_enabled
    ap = argparse.ArgumentParser(description="All-in-one cookie defense (single file).")
    ap.add_argument("--browser", choices=["brave", "chrome"], default=None)
    ap.add_argument("--audit", action="store_true", help="list risky extensions and exit")
    ap.add_argument("--save-baseline", action="store_true", help="save trusted extension set and exit")
    ap.add_argument("--include-webrequest", action="store_true", help="also flag webRequest.* (noisier)")
    ap.add_argument("--burst", type=int, default=3, help="theft alert after this many cookie reads in the burst window (default 3)")
    ap.add_argument("--burst-window", type=int, default=10, help="seconds for the burst window (default 10)")
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args()

    browser = args.browser or detect_browser()
    _notify_enabled = not args.no_notify

    if args.audit:
        print_audit(browser)
        return
    if args.save_baseline:
        save_baseline(browser)
        return

    print("=" * 62)
    print("  COOKIE GUARD — single-file background defense")
    print("=" * 62)
    print(f"Browser     : {browser}")
    print(f"Unified log : {LOG.name}")
    print("Stop        : Ctrl+C\n")
    if not BASELINE.exists():
        print("Tip: run  python cookie_guard.py --browser brave --save-baseline  once,")
        print("     so the hourly check can alert on NEW cookie-capable extensions.\n")
    log("Cookie Guard started")

    threads = [
        threading.Thread(target=extension_watch_thread, args=(browser, args.include_webrequest, args.burst, args.burst_window), daemon=True),
        threading.Thread(target=file_watch_thread, args=(browser,), daemon=True),
        threading.Thread(target=diff_thread, args=(browser,), daemon=True),
    ]
    for t in threads:
        t.start()
    print("\nAll watchers running. Waiting for cookie access...\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        stop.set()
        time.sleep(2)
        log("Cookie Guard stopped")
        print("Stopped.")


if __name__ == "__main__":
    main()

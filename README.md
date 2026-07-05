# 🍪 Cookie Guard

**A simple background tool that tells you — by name — whenever an extension or program reads your browser cookies, and shouts louder when something acts like a thief.**

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2011-lightgrey)
![Browser](https://img.shields.io/badge/browser-Brave%20%7C%20Chrome-orange)
![License](https://img.shields.io/badge/license-MIT-green)
![Version](https://img.shields.io/badge/version-1.1-blueviolet)

Cookie Guard watches your Brave (or Chrome) cookies and **raises an alert the moment something touches them** — naming the exact extension or program responsible. It's one small Python file. No installer, no account, no admin rights.

> ⚠️ **Cookie Guard is an alarm, not a lock.** It *tells you* when your cookies are read; it does not block the read. Treat an alert as "investigate now," not "you're protected."

---

## 📑 Table of Contents
- [Why this exists](#-why-this-exists)
- [What it does](#-what-it-does)
- [Two alert levels](#-two-alert-levels)
- [How it works](#-how-it-works)
- [Example alerts](#-example-alerts)
- [Requirements](#-requirements)
- [Installation](#-installation)
- [One-time setup (important)](#-one-time-setup-important)
- [How to use it](#-how-to-use-it)
- [Understanding the alerts](#-understanding-the-alerts)
- [Run it in the background](#-run-it-in-the-background)
- [Honest limitations](#-honest-limitations)
- [FAQ](#-faq)
- [Staying safe](#-staying-safe)
- [License](#-license)

---

## 🎯 Why this exists

Your **cookies** are what keep you logged in to websites. Some of them are **session tokens** — if someone copies one, they can log in *as you* without your password. This is called **cookie hijacking** or **session hijacking**.

Two things can steal cookies:

1. **A bad browser extension** — one you installed that quietly reads your cookies.
2. **Malware or shady software** — a program on your PC that reads the browser's cookie file off the disk.

The frustrating part: a normal person has **no way to see this happening**. Browsers hide one extension's activity from everything else, and malware copies files silently.

**Cookie Guard closes that blind spot.** It watches both paths and names the culprit.

---

## ✨ What it does

| # | Watcher | Catches | Tells you |
|---|---------|---------|-----------|
| 1 | **Extension watch** | An **extension** reading cookies | Which extension, which call, which cookie — and whether it's behaving like a **thief** |
| 2 | **File watch** | An **external program** opening the cookie file | Which program, its path, which file |
| 3 | **Hourly audit** | A **new** cookie-capable extension being installed | The new extension's name and risk level |

Every alert is shown on screen, popped as a desktop notification, and saved to `cookie_guard.log`.

---

## 🚦 Two alert levels

The smart part: not every cookie read is bad. Some extensions **legitimately** need to read a cookie to do their job. A thief is different — a thief grabs **lots** of cookies **fast**. So Cookie Guard sorts extension activity into two levels:

| Level | Alert name | When it fires | What it means |
|-------|-----------|---------------|---------------|
| 🟡 **Normal read** | `EXTENSION READ A COOKIE` | An extension reads a cookie | Probably fine — the extension doing its job. Shown so you never lose visibility. |
| 🔴 **Theft pattern** | `POSSIBLE COOKIE THEFT` | An extension reads **3+ cookies in a short burst**, OR makes a **bulk-dump call** (`cookies.getAll` / `debugger`) | Acting like a stealer — grabbing a pile of cookies at once. **Stop and check this extension.** |

**In plain words:** one extension quietly reading its own single cookie = normal. An extension suddenly reading several login cookies, or dumping them all at once = **theft alert**.

You can tune the sensitivity (see [commands](#-how-to-use-it)):
- `--burst 5` → wait for 5 reads instead of 3 before the theft alert (fewer alerts)
- `--burst-window 10` → change the "short burst" window to 10 seconds

---

## ⚙️ How it works

```mermaid
flowchart TD
    A[Cookie Guard running] --> B[Extension Watch]
    A --> C[File Watch]
    A --> D[Hourly Audit]
    B -->|reads Brave's Extension Activity log| E{Extension read a cookie?}
    E -->|one cookie| Y[🟡 Normal read alert]
    E -->|3+ fast, or getAll/debugger| R[🔴 POSSIBLE THEFT alert]
    C -->|asks Windows who has the file open| F{Non-Brave program<br/>opened the cookie file?}
    D -->|compares to your saved baseline| G{New cookie-capable<br/>extension appeared?}
    F -->|yes| H[🚨 ALERT + notification + log]
    G -->|yes| H
    Y --> H
    R --> H
```

In plain English:

- **Extension watch** reads a log that Brave/Chrome can keep of everything your extensions do. When an extension calls a cookie function, Cookie Guard sees it, and decides if it's a normal read or a theft pattern.
- **File watch** asks Windows directly, *"which programs currently have my cookie file open?"* If it's anything other than the real Brave, you get an alert.
- **Hourly audit** notices which extensions can read cookies, and warns you if a **new** one appears that you didn't have before.

---

## 🖥️ Example alerts

**🟡 A normal read** (extension doing its job):

```
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  EXTENSION READ A COOKIE
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  extension : Some Extension (abcdefgh...)
  api call  : cookies.get
  cookie    : session_pref
  time      : 2026-07-04 18:59:46
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
```

**🔴 A theft pattern** (grabbing many cookies fast):

```
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  POSSIBLE COOKIE THEFT  (RAPID BURST)
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  extension : Some Extension (abcdefgh...)
  read      : 6 cookies in <= 10s
  cookies   : auth-token-data, sessionid, sid, __Secure-1PSID, login
  time      : 2026-07-04 19:01:12
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
```

The theft alert lists the extension **name**, how many cookies it grabbed, and **which ones**. Login-type cookies (`auth`, `session`, `sid`, `login`…) in that list are the ones that matter most.

---

## 📦 Requirements

- **Windows 11** (Windows 10 also works)
- **Brave** or **Google Chrome**
- **Python 3.8 or newer** — get it from [python.org](https://www.python.org/downloads/) (during install, tick **"Add Python to PATH"**)
- One optional Python package for desktop pop-ups:

```bash
pip install plyer
```

> The tool still works without `plyer` — you'll just get on-screen and log alerts instead of pop-ups.

---

## 🚀 Installation

1. Download `cookie_guard.py` from this repository (green **Code** button → **Download ZIP**, or just save the file).
2. Put it in a folder you'll remember, for example `C:\Users\YourName\CookieGuard`.
3. Open **PowerShell** in that folder (Shift + right-click the folder → *Open PowerShell window here*).

That's it — there's nothing to install for the tool itself. It's one file.

---

## 🔧 One-time setup (important)

The **Extension watch** needs Brave/Chrome to keep an activity log, which is **turned off by default**. Turn it on once:

1. **Fully quit Brave** (also check the tray icon near the clock).
2. **Right-click** your Brave shortcut → **Properties**.
3. In the **Target** box, add a space and this at the very end:
   ```
   --enable-extension-activity-logging
   ```
   It should look like:
   ```
   "C:\...\Brave-Browser\Application\brave.exe" --enable-extension-activity-logging
   ```
4. Click **Apply** → **OK**.
5. **Always open Brave from this shortcut** from now on.

> 💡 You can check it's working in the browser: go to `brave://extensions`, turn on **Developer mode**, open any extension's **Details**, and click **View activity log**.

The **File watch** needs no setup — it works right away.

---

## ▶️ How to use it

**Start it (main mode):**
```bash
python cookie_guard.py --browser brave
```
Leave the window open. It quietly watches and alerts you when something reads your cookies.

**Save your "trusted" list once**, so the hourly check can spot new extensions later:
```bash
python cookie_guard.py --browser brave --save-baseline
```

**All commands:**

| Command | What it does |
|---------|--------------|
| `--browser chrome` | Watch Chrome instead of Brave |
| `--audit` | Just list your cookie-capable extensions and exit |
| `--save-baseline` | Remember your current extensions as trusted |
| `--burst 5` | Theft alert after this many cookies in a burst (default **3**) |
| `--burst-window 10` | Length of the "short burst" window in seconds (default 10) |
| `--include-webrequest` | Also flag `webRequest` activity (noisier; good for testing) |
| `--no-notify` | No desktop pop-ups (screen + log only) |

**Stop it:** press `Ctrl + C`.

---

## 🔍 Understanding the alerts

| Alert | Meaning | What to do |
|-------|---------|------------|
| 🟡 **EXTENSION READ A COOKIE** | An extension read one cookie | Usually fine. Note it if the extension has no reason to touch cookies. |
| 🔴 **POSSIBLE COOKIE THEFT (RAPID BURST)** | An extension read many cookies fast | **Stop and check.** If you don't fully trust it, remove it and revoke sessions. |
| 🔴 **POSSIBLE COOKIE THEFT (BULK-DUMP CALL)** | An extension used `getAll` / `debugger` to grab all cookies | **High suspicion.** Very few honest extensions need this. |
| **EXTERNAL PROGRAM OPENED YOUR COOKIE FILE** | A non-Brave program opened the cookie file | If you don't recognize the program, scan for malware and revoke sessions. |
| **NEW COOKIE-CAPABLE EXTENSION APPEARED** | A new extension with cookie access showed up | Make sure *you* installed it on purpose. |

**If you get a real alert you can't explain:**
1. Remove the extension / close the program.
2. Log out of your important accounts **from a different device** (or change the password) — this makes any stolen cookie useless.
3. Run a malware scan.

> 🔑 **Important:** clearing your browser history does **not** protect you from an already-stolen cookie — the thief has their own copy. Only **logging out / changing your password** (which ends the session on the website's side) makes a stolen cookie useless.

---

## 🌙 Run it in the background

**Option A — hidden, no window:** double-click `run_hidden.vbs`. Nothing appears, but it's running. You still get pop-ups and the log. To stop it, double-click `stop_cookie_guard.bat`.

**Option B — start automatically at login:**
1. Press `Win + R`, type `shell:startup`, press Enter.
2. Copy a **shortcut** to `run_hidden.vbs` into that folder.

> Background extension-watching only works if Brave was launched with the activity-logging flag from the setup step. Keep using your edited Brave shortcut. Also: run **only one** copy of Cookie Guard at a time — two copies will flag each other.

---

## ⚖️ Honest limitations

Please read this so you trust the tool the right amount:

- **It's an alarm, not a lock.** It reports access *after* it happens. It does not block it.
- **A theft alert is a strong signal, not proof.** A few honest tools (a password manager, a backup/export tool you trust) might read several cookies too. Always check *which* extension it is and whether that behavior fits its job.
- **It can't catch every trick.** A very advanced attacker could read cookies in ways that don't show up as a normal cookie call or file open. Cookie Guard catches the **common** methods — most of them, not all.
- **Extension watch needs the activity-log flag.** Without the one-time setup, only the file watch runs.
- **File watch is Windows-only** (it uses a Windows feature). The extension watch works on any OS where the browser writes the activity log.

**The best protection is still prevention:** only install extensions you trust, keep your browser updated, and ask *"why does this extension need cookie access?"* before installing.

---

## ❓ FAQ

**Does this change how my browser works?**
No. Brave looks and behaves exactly the same. The tool only *reads* logs and file info.

**Is it safe / does it steal anything?**
Cookie Guard is purely defensive. It never decrypts your cookie values and never sends anything anywhere. It only watches and alerts, locally, on your PC.

**Why did it flag Python / my own script?**
The file watch flags *any* non-Brave program that opens the cookie file — including your own test scripts. Check the program name: if it's something you started, it's expected.

**Will it slow down my PC?**
No noticeable impact. It checks quietly every 1–2 seconds.

**I got "Extension activity log is OFF."**
You opened Brave from a shortcut without the flag. Redo the [one-time setup](#-one-time-setup-important).

**Can I use it for Chrome?**
Yes — add `--browser chrome` and use a Chrome shortcut with the same flag.

---

## 🛡️ Staying safe

- Only install extensions from the official store, and only ones you actually need.
- Be suspicious of extensions asking for **cookie** or **all-sites** access when their job doesn't need it.
- Keep Brave/Chrome updated (modern versions make stolen cookie files harder to use).
- Log out of important accounts when you're done; short sessions = smaller risk.
- If in doubt after an alert: change your password from a trusted device — it ends existing sessions.

---

## 📄 License

MIT License — free to use, change, and share. See [LICENSE](LICENSE).

---

*Made for personal, defensive use on your own computer. Stay safe out there. 🍪🛡️*

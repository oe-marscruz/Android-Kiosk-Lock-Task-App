"""
CU Denver Equity - Kiosk Manager GUI
A simple tool for non-technical users to set up and manage the kiosk tablet.
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import os
import sys
import threading

# ---------- paths (support PyInstaller runtime + macOS) ----------
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

EXE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))

# Platform-specific ADB binary
if sys.platform == "darwin":
    ADB = os.path.join(BASE_DIR, "platform-tools", "adb")
elif sys.platform == "win32":
    ADB = os.path.join(BASE_DIR, "platform-tools", "adb.exe")
else:
    ADB = os.path.join(BASE_DIR, "platform-tools", "adb")

# APK: bundled inside .exe when frozen, alongside when running as script
if getattr(sys, 'frozen', False):
    APK = os.path.join(BASE_DIR, "CU-Denver-Equity-Kiosk.apk")
else:
    APK = os.path.join(EXE_DIR, "build", "CU-Denver-Equity-Kiosk.apk")
PACKAGE = "com.example.webkiosk"
DPC_PACKAGE = PACKAGE
DPC = "com.example.webkiosk/.KioskDeviceAdminReceiver"


def run_cmd(cmd, timeout=30):
    """Run a command and return (stdout, stderr, returncode)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, shell=True)
        return r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 1
    except Exception as e:
        return "", str(e), 1


def adb(cmd_args, timeout=30):
    """Run an ADB command."""
    return run_cmd(f'"{ADB}" {cmd_args}', timeout)


# ---------- GUI ----------
class KioskManager:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CU Denver Equity - Kiosk Manager")
        self.root.geometry("620x520")
        self.root.minsize(500, 420)
        self.is_fullscreen = False

        # keyboard shortcuts
        self.root.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.root.bind("<Escape>", lambda e: self.exit_fullscreen())

        # style
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.is_dark = False
        self.is_a11y = False
        self._base_font_size = 10

        # widget registry for theme switching
        self._tk_widgets = []
        self._all_buttons = []

        # header
        self.header = tk.Label(self.root, text="CU Denver Equity — Kiosk Manager",
                                font=("Segoe UI", 16, "bold"), fg="#1a3c6d")
        self.header.pack(pady=(15, 5))
        self._tk_widgets.append(self.header)

        self.sub = tk.Label(self.root,
                             text="Lock a Lenovo tablet to the equity office website.",
                             font=("Segoe UI", 10), fg="#555")
        self.sub.pack()
        self._tk_widgets.append(self.sub)

        # ---------- connection status ----------
        self.status_frame = ttk.LabelFrame(self.root, text="Device Status", padding=10)
        self.status_frame.pack(fill="x", padx=20, pady=(15, 5))

        self.status_label = tk.Label(self.status_frame, text="Checking...",
                                     font=("Segoe UI", 10), fg="#888")
        self.status_label.pack(anchor="w")

        self.status_details = tk.Label(self.status_frame, text="",
                                       font=("Segoe UI", 9), fg="#666")
        self.status_details.pack(anchor="w")

        # ---------- buttons ----------
        self.btn_frame = ttk.Frame(self.root)
        self.btn_frame.pack(pady=10)

        ttk.Button(self.btn_frame, text="🔒  Setup Kiosk",
                   command=self.setup_kiosk, width=20).pack(side="left", padx=5)
        ttk.Button(self.btn_frame, text="🔓  Exit Kiosk",
                   command=self.exit_kiosk, width=20).pack(side="left", padx=5)
        ttk.Button(self.btn_frame, text="📱  Restore All Apps",
                   command=self.restore_all_apps, width=20).pack(side="left", padx=5)

        # ---------- remote management ----------
        remote_frame = ttk.Frame(self.root)
        remote_frame.pack(pady=(5, 0))

        ttk.Button(remote_frame, text="🌐  Setup Remote Management",
                   command=self.setup_remote_mgmt, width=25).pack(side="left", padx=5)
        tk.Label(remote_frame, text="Optional: enroll tablet in Android Management API for cloud control.",
                 font=("Segoe UI", 7), fg="#888").pack(side="left", padx=5)

        # ---------- view controls ----------
        self.view_frame = ttk.Frame(self.root)
        self.view_frame.pack(pady=(0, 5))

        self.fs_btn = ttk.Button(self.view_frame, text="🗖  Fullscreen (F11)",
                                 command=self.toggle_fullscreen, width=18)
        self.fs_btn.pack(side="left", padx=5)
        self._all_buttons.append(self.fs_btn)

        self.dark_btn = ttk.Button(self.view_frame, text="🌙  Dark Mode",
                                    command=self.toggle_dark_mode, width=16)
        self.dark_btn.pack(side="left", padx=5)
        self._all_buttons.append(self.dark_btn)

        self.a11y_btn = ttk.Button(self.view_frame, text="♿  Accessibility",
                                    command=self.toggle_accessibility, width=17)
        self.a11y_btn.pack(side="left", padx=5)
        self._all_buttons.append(self.a11y_btn)

        # ---------- dangerous actions ----------
        self.danger_frame = ttk.Frame(self.root)
        self.danger_frame.pack(pady=(0, 5))

        ttk.Button(self.danger_frame, text="⚠  Factory Reset Tablet",
                   command=self.factory_reset, width=25).pack()
        self.danger_label = tk.Label(self.danger_frame,
                 text="This erases ALL data and returns the tablet to its original state.",
                 font=("Segoe UI", 8), fg="#c0392b")
        self.danger_label.pack()
        self._tk_widgets.append(self.danger_label)

        # ---------- log ----------
        self.log_frame = ttk.LabelFrame(self.root, text="Log", padding=5)
        self.log_frame.pack(fill="both", expand=True, padx=20, pady=(5, 15))

        self.log = scrolledtext.ScrolledText(self.log_frame, height=12,
                                             font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)

        # ---------- instructions ----------
        self.instr = tk.Label(self.root,
                          text="1. Connect tablet via USB  2. Tap 'Setup Kiosk'  "
                               "3. Open CU Denver Equity app on tablet",
                          font=("Segoe UI", 9, "italic"), fg="#888")
        self.instr.pack(pady=(0, 10))
        self._tk_widgets.append(self.instr)

        self.check_status()
        self.root.mainloop()

    # ---------- helpers ----------
    def log_add(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.root.update_idletasks()

    def set_status(self, text, detail="", color="#000"):
        self.status_label.config(text=text, fg=color)
        self.status_details.config(text=detail)

    def run_in_thread(self, target, *args):
        threading.Thread(target=target, args=args, daemon=True).start()

    # ---------- fullscreen ----------
    def toggle_fullscreen(self):
        if self.is_fullscreen:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        self.root.attributes("-fullscreen", True)
        self.is_fullscreen = True
        self.fs_btn.config(text="🗗  Exit Fullscreen (Esc)")
        self.log_add("Fullscreen enabled (Esc or F11 to exit)")

    def exit_fullscreen(self, event=None):
        if self.is_fullscreen:
            self.root.attributes("-fullscreen", False)
            self.is_fullscreen = False
            self.fs_btn.config(text="🗖  Fullscreen (F11)")
            self.log_add("Fullscreen disabled")

    # ---------- dark mode ----------
    def toggle_dark_mode(self):
        self.is_dark = not self.is_dark
        self.apply_theme()
        mode = "on" if self.is_dark else "off"
        self.dark_btn.config(text="☀  Light Mode" if self.is_dark else "🌙  Dark Mode")
        self.log_add(f"Dark mode {mode}")

    def apply_theme(self):
        if self.is_dark:
            bg = "#1e1e1e"
            fg = "#d4d4d4"
            dim = "#888888"
            log_bg = "#2d2d2d"
            log_fg = "#cccccc"
            entry_bg = "#3c3c3c"
            sel_bg = "#264f78"
        else:
            bg = "#f0f0f0"
            fg = "#000000"
            dim = "#555555"
            log_bg = "#ffffff"
            log_fg = "#000000"
            entry_bg = "#ffffff"
            sel_bg = "#0078d7"

        # root
        self.root.configure(bg=bg)

        # tk labels
        for w in self._tk_widgets:
            try:
                if w is self.danger_label:
                    w.configure(bg=bg, fg="#e06c75" if self.is_dark else "#c0392b")
                elif w is self.instr:
                    w.configure(bg=bg, fg=dim)
                else:
                    w.configure(bg=bg, fg=fg)
            except Exception:
                pass

        # header special
        try:
            self.header.configure(bg=bg, fg="#569cd6" if self.is_dark else "#1a3c6d")
        except Exception:
            pass

        # status labels
        try:
            self.status_label.configure(bg=bg)
            self.status_details.configure(bg=bg)
        except Exception:
            pass

        # log widget
        try:
            self.log.configure(bg=log_bg, fg=log_fg,
                               insertbackground=log_fg,
                               selectbackground=sel_bg)
        except Exception:
            pass

        # ttk style
        self.style.configure("TFrame", background=bg)
        self.style.configure("TLabelframe", background=bg)
        self.style.configure("TLabelframe.Label", background=bg, foreground=fg)
        self.style.configure("TButton", background=entry_bg, foreground=fg)
        self.style.map("TButton",
                       background=[("active", sel_bg), ("!disabled", entry_bg)],
                       foreground=[("active", "#ffffff")])

    # ---------- accessibility ----------
    def toggle_accessibility(self):
        self.is_a11y = not self.is_a11y
        self.apply_accessibility()
        state = "on" if self.is_a11y else "off"
        self.a11y_btn.config(text="♿  Accessibility ✓" if self.is_a11y else "♿  Accessibility")
        self.log_add(f"Accessibility mode {state} — larger text + high contrast")

    def apply_accessibility(self):
        if self.is_a11y:
            scale = 1.4
            btn_pad = (12, 8)
            log_font = ("Consolas", 12, "bold")
            focus_width = 3
            focus_color = "#ffcc00"
        else:
            scale = 1.0
            btn_pad = (1, 1)
            log_font = ("Consolas", 9)
            focus_width = 1
            focus_color = ""

        # Scale font sizes
        sizes = {
            self.header: ("Segoe UI", int(16 * scale), "bold"),
            self.sub: ("Segoe UI", int(10 * scale)),
            self.status_label: ("Segoe UI", int(10 * scale)),
            self.status_details: ("Segoe UI", int(9 * scale)),
            self.instr: ("Segoe UI", int(9 * scale), "italic"),
            self.danger_label: ("Segoe UI", int(8 * scale)),
        }
        for widget, fontspec in sizes.items():
            try:
                widget.configure(font=fontspec)
            except Exception:
                pass

        # Log font
        try:
            self.log.configure(font=log_font)
        except Exception:
            pass

        # Button padding
        for btn in self._all_buttons:
            try:
                btn.configure(padding=btn_pad)
            except Exception:
                pass

        # Focus highlight for all widgets
        for w in self._tk_widgets + [self.status_label, self.status_details]:
            try:
                w.configure(highlightthickness=focus_width,
                            highlightbackground=focus_color,
                            highlightcolor=focus_color)
            except Exception:
                pass

        # Window size adjustment for larger text
        if self.is_a11y:
            self.root.geometry("720x620")
            self.root.minsize(600, 500)
        else:
            self.root.geometry("620x520")
            self.root.minsize(500, 420)

    # ---------- actions ----------
    def check_status(self):
        def _check():
            self.log_add("--- Checking device status ---")
            out, err, rc = adb("devices")
            lines = [l for l in out.splitlines() if l.strip() and "List" not in l]
            if not lines:
                self.set_status("❌ No device connected",
                                "Plug in the tablet via USB and enable USB Debugging.",
                                "#c00")
                self.log_add("No device found.")
                return
            device_line = lines[0]
            if "unauthorized" in device_line:
                self.set_status("⚠️  Device unauthorized",
                                "Tap 'Allow' on the tablet screen.", "#e67e00")
                return
            self.set_status("✅ Device connected",
                            device_line.split()[0], "#1a7a1a")
            self.log_add(f"Connected: {device_line}")

            # check lock task allowlist
            out, err, rc = adb("shell dumpsys device_policy 2>nul | findstr \"LockTaskPolicy\"")
            if "com.example.webkiosk" in out:
                self.log_add("Kiosk app is allowlisted. ✅")
            else:
                self.log_add("Kiosk app NOT allowlisted yet.")

        self.run_in_thread(_check)

    def setup_kiosk(self):
        def _setup():
            self.log_add("\n=== SETTING UP KIOSK ===")

            # Step 1: check device
            self.log_add("[1/6] Checking connection...")
            out, err, rc = adb("devices")
            if "device" not in out or "unauthorized" in out:
                self.log_add("ERROR: Device not ready. Connect tablet and accept prompt.")
                messagebox.showerror("Error", "Device not connected or unauthorized.\nConnect USB and accept the debugging prompt.")
                return

            # Step 2: install kiosk APK (must be installed before device owner)
            self.log_add("[2/6] Installing kiosk APK...")
            if not os.path.exists(APK):
                self.log_add(f"APK not found: {APK}")
                self.log_add("Run setup-kiosk.bat first to build the APK.")
                messagebox.showerror("Error", "APK not found.\nRun setup-kiosk.bat to build it first.")
                return
            out, err, rc = adb(f'install -r "{APK}"')
            if "Success" in out:
                self.log_add("APK installed successfully. ✅")
            elif "UPDATE_INCOMPATIBLE" in err:
                self.log_add("Signature mismatch, reinstalling...")
                adb(f"uninstall {PACKAGE}")
                out2, err2, rc2 = adb(f'install "{APK}"')
                if "Success" in out2:
                    self.log_add("APK reinstalled. ✅")
                else:
                    self.log_add(f"Install failed: {err2}")

            # Step 3: set the kiosk app as device owner
            self.log_add("[3/6] Setting kiosk app as device owner...")
            out, err, rc = adb(f"shell dpm set-device-owner {DPC}")
            if "Success" in out or "already" in err.lower():
                self.log_add("Device owner OK. ✅")
            else:
                self.log_add(f"Note: {err.strip() or out.strip()}")
                self.log_add("If Test DPC was the previous device owner, you may need to factory reset first.")

            # Step 4: set custom launcher as default home
            self.log_add("[4/6] Setting kiosk launcher as default home...")
            out, err, rc = adb(
                "shell cmd package set-home-activity"
                " com.example.webkiosk/com.example.kiosklauncher.LauncherActivity")
            if rc == 0:
                self.log_add("Custom launcher set as home. ✅")
            else:
                self.log_add("Note: launcher may already be set.")

            # Step 5: hide non-essential apps
            self.log_add("[5/6] Securing app drawer — hiding non-essential apps...")
            out, err, rc = adb(
                "shell pm query-activities --brief"
                " -a android.intent.action.MAIN"
                " -c android.intent.category.LAUNCHER")
            if rc == 0:
                hidden = 0
                for line in out.splitlines():
                    if line.strip().startswith("com."):
                        pkg = line.strip().split("/")[0]
                        if pkg not in (PACKAGE, "com.google.android.deskclock"):
                            adb(f"shell pm disable-user --user 0 {pkg}")
                            hidden += 1
                self.log_add(f"  {hidden} apps hidden from app drawer. ✅")
                self.log_add("  Keeping: Kiosk, Clock.")
            else:
                self.log_add("  Could not query app drawer.")

            # Step 6: verify lock task allowlist
            self.log_add("[6/6] Checking lock task allowlist...")
            out, err, rc = adb("shell dumpsys device_policy 2>nul | findstr \"LockTaskPolicy\"")
            if PACKAGE in out:
                self.log_add("Kiosk app is allowlisted for lock task mode. ✅")
                if "com.android.chrome" in out:
                    self.log_add("Chrome is allowlisted. ✅")
                else:
                    self.log_add("Chrome not allowlisted yet — open the kiosk app once to apply the allowlist.")
                if "com.android.settings" in out:
                    self.log_add("WiFi settings are allowlisted. ✅")
                else:
                    self.log_add("WiFi settings not allowlisted yet — open the kiosk app once to apply the allowlist.")
            else:
                self.log_add("App NOT allowlisted — open the kiosk app once so it can configure lock task mode.")

            self.log_add("\n=== DONE ===")
            self.log_add("Tap 'CU Denver Equity' on the tablet to enter kiosk mode.")
            self.check_status()
            messagebox.showinfo("Setup Complete",
                                "Kiosk is ready!\n\n"
                                "On the tablet, tap 'CU Denver Equity' to enter\n"
                                "kiosk mode. Chrome and WiFi settings can now\n"
                                "run in lock task mode.")

        self.run_in_thread(_setup)

    def exit_kiosk(self):
        def _exit():
            self.log_add("\n=== EXITING KIOSK MODE ===")
            self.log_add("Stopping kiosk app...")
            out, err, rc = adb(f"shell am force-stop {PACKAGE}")
            self.log_add("App stopped. Tablet should return to home screen. ✅")
            self.log_add("To fully remove: Settings > Security > Device Admin Apps > deactivate the kiosk app")
            self.check_status()
            messagebox.showinfo("Kiosk Exited",
                                "The kiosk app has been stopped.\n\n"
                                "Your tablet should be back to normal.")

        self.run_in_thread(_exit)

    def restore_all_apps(self):
        """Re-enable all apps that were hidden."""
        if not messagebox.askyesno(
            "Restore All Apps",
            "This will re-enable ALL previously hidden apps\n"
            "(Chrome, Settings, Play Store, YouTube, etc.).\n\n"
            "Use this after exiting kiosk mode to return\n"
            "the tablet to normal use.\n\n"
            "Continue?",
            icon="info"):
            return

        def _restore():
            self.log_add("\n=== RESTORING ALL APPS ===")
            out, err, rc = adb("shell pm list packages -d")
            count = 0
            for line in out.splitlines():
                if line.startswith("package:"):
                    pkg = line[8:].strip()
                    adb(f"shell pm enable {pkg}")
                    count += 1
            self.log_add(f"Re-enabled {count} apps. ✅")
            self.log_add("App drawer is fully restored.")
            self.check_status()
            messagebox.showinfo("Apps Restored",
                                f"{count} apps have been re-enabled.\n\n"
                                "The tablet app drawer is back to normal.")

        self.run_in_thread(_restore)

    def setup_remote_mgmt(self):
        """Guide user through Android Management API enrollment."""
        # Step 1: show instructions
        if not messagebox.askyesno(
            "Remote Management Setup",
            "Android Management API lets you control the tablet\n"
            "remotely through a web dashboard.\n\n"
            "Prerequisites:\n"
            "  • A Google account (for the admin console)\n"
            "  • The tablet will be factory reset\n"
            "  • Internet access on the tablet\n\n"
            "This is optional — local USB/Wi-Fi ADB still works.\n\n"
            "Continue?",
            icon="info"):
            return

        # Step 2: open the Google enrollment console
        self.log_add("\n=== REMOTE MANAGEMENT SETUP ===")
        self.log_add("Opening Google Android Enterprise console...")
        import webbrowser
        webbrowser.open("https://business.android.com/enterprise")

        self.log_add("")
        self.log_add("=== INSTRUCTIONS ===")
        self.log_add("1. Sign in with a Google account")
        self.log_add("2. Create an enterprise (your organization name)")
        self.log_add("3. In the console, go to Devices → Enrollment")
        self.log_add("4. Generate an enrollment token or QR code")
        self.log_add("5. Copy the enrollment token (starts with 'afw#setup')")
        self.log_add("")

        # Step 3: ask for the token
        token = self.prompt_for_token()
        if not token:
            self.log_add("Setup cancelled.")
            return

        self.log_add(f"Token received: {token[:20]}...")

        # Step 4: factory reset the tablet
        if not messagebox.askyesno(
            "Factory Reset Required",
            "The tablet must be factory reset to enroll\n"
            "in Android Management API.\n\n"
            "This will erase ALL data on the tablet.\n\n"
            "A QR code will be displayed on this screen\n"
            "for the tablet to scan during setup.\n\n"
            "Continue with factory reset?",
            icon="warning"):
            self.log_add("Remote setup cancelled.")
            return

        self.log_add("Factory resetting tablet...")
        adb("shell recovery --wipe_data")

        # Step 5: show QR code
        self.show_enrollment_qr(token)

    def prompt_for_token(self):
        """Open a dialog to paste the enrollment token."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Enter Enrollment Token")
        dialog.geometry("500x200")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Paste the enrollment token from the console below:",
                 font=("Segoe UI", 10)).pack(pady=(15, 5))
        tk.Label(dialog,
                 text="(Starts with 'afw#setup' or is a long alphanumeric code)",
                 font=("Segoe UI", 8), fg="#888").pack()

        entry = tk.Entry(dialog, font=("Consolas", 10), width=55)
        entry.pack(pady=(10, 15))

        result = []

        def on_ok():
            result.append(entry.get().strip())
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        btn_frame = tk.Frame(dialog)
        btn_frame.pack()
        tk.Button(btn_frame, text="OK", command=on_ok, width=12,
                  font=("Segoe UI", 9)).pack(side="left", padx=5)
        tk.Button(btn_frame, text="Cancel", command=on_cancel, width=12,
                  font=("Segoe UI", 9)).pack(side="left", padx=5)

        dialog.wait_window()
        return result[0] if result else None

    def show_enrollment_qr(self, token):
        """Display QR code for tablet enrollment."""
        try:
            import qrcode
        except ImportError:
            self.log_add("")
            self.log_add("QR code library not installed.")
            self.log_add(f"Manually enter this token on the tablet:")
            self.log_add(f"  {token}")
            self.log_add("")
            self.log_add("During setup, tap the welcome screen 6 times")
            self.log_add("and enter the token when prompted.")
            return

        img = qrcode.make(token)

        qr_window = tk.Toplevel(self.root)
        qr_window.title("Scan This QR Code")
        qr_window.geometry("350x450")
        qr_window.transient(self.root)

        tk.Label(qr_window,
                 text="After the tablet reboots to the setup screen:\n"
                      "Tap the welcome text 6 times, then scan this QR code.",
                 font=("Segoe UI", 9), wraplength=300).pack(pady=10)

        # Convert PIL image to tkinter-compatible
        import io
        from PIL import ImageTk
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        photo = ImageTk.PhotoImage(img.resize((250, 250)))

        label = tk.Label(qr_window, image=photo)
        label.image = photo
        label.pack(pady=10)

        tk.Label(qr_window,
                 text=f"Token: {token[:30]}...",
                 font=("Consolas", 8), wraplength=300).pack(pady=5)

        tk.Button(qr_window, text="Close", command=qr_window.destroy,
                  width=12).pack(pady=10)

    def factory_reset(self):
        """Factory reset the tablet - wipes everything."""
        if not messagebox.askyesno(
            "⚠ FACTORY RESET — ARE YOU SURE?",
            "This will permanently ERASE ALL DATA on the tablet:\n\n"
            "  • All apps will be removed\n"
            "  • All accounts will be deleted\n"
            "  • All settings will be reset\n"
            "  • Device owner will be cleared\n\n"
            "The tablet will reboot and return to the\n"
            "initial setup screen (like when it was new).\n\n"
            "This CANNOT be undone.\n\n"
            "Are you absolutely sure you want to continue?",
            icon="warning"):
            return

        # second confirmation
        if not messagebox.askyesno(
            "⚠ FINAL WARNING",
            "This is your last chance to cancel.\n\n"
            "Tap 'Yes' ONLY if you are certain you\n"
            "want to factory reset this tablet.",
            icon="error"):
            return

        def _reset():
            self.log_add("\n=== FACTORY RESET ===")
            self.log_add("⚠ Wiping tablet — this takes about 2-5 minutes...")

            # Method 1: recovery --wipe_data (works on most devices)
            self.log_add("Sending wipe command...")
            out, err, rc = adb("shell recovery --wipe_data")
            self.log_add(out.strip() if out.strip() else "Command sent.")

            if rc != 0 or "not found" in (out + err).lower():
                # Method 2: broadcast MASTER_CLEAR (works on many newer devices)
                self.log_add("Trying alternate method...")
                out, err, rc = adb(
                    "shell am broadcast -a android.intent.action.MASTER_CLEAR "
                    "-n android/com.android.server.MasterClearReceiver"
                )
                self.log_add(out.strip() if out.strip() else "Broadcast sent.")

            if rc != 0:
                # Method 3: reboot to recovery (user must navigate manually)
                self.log_add("Trying reboot to recovery...")
                out, err, rc = adb("reboot recovery")
                self.log_add(
                    "Tablet is rebooting to recovery mode.\n"
                    "On the tablet screen, use the volume buttons to navigate\n"
                    "to 'Wipe data/factory reset' and press the power button\n"
                    "to select it."
                )

            self.log_add("\nFactory reset initiated. The tablet will reboot shortly.")
            self.log_add("After reboot, you'll need to set up the tablet from scratch.")
            self.check_status()

        self.run_in_thread(_reset)


# ---------- entry ----------
def main():
    # check ADB
    if not os.path.exists(ADB):
        msg = ("ADB not found.\n\n"
               "Please run setup-tools.bat first to install\n"
               "the required developer tools.")
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Missing Tools", msg)
        root.destroy()
        sys.exit(1)

    KioskManager()


if __name__ == "__main__":
    main()

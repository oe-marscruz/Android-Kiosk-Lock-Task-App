"""
CU Denver Equity - Kiosk Manager GUI
A simple tool for non-technical users to set up and manage the kiosk tablet.
"""
import os
import sys
import bundle_resources

if __name__ == "__main__" and sys.argv[1:2] == ["--check-bundle"]:
    sys.exit(bundle_resources.main(sys.argv[2:]))

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import queue
import threading

import package_policy
import provisioning

# ---------- paths (support PyInstaller runtime + macOS) ----------
BASE_DIR, ADB, APK = bundle_resources.resource_paths()

EXE_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))

PACKAGE_STATE = package_policy.default_state_path()


# ---------- GUI ----------
class KioskManager:
    def __init__(self):
        self.root = tk.Tk()
        self._events = queue.Queue()
        self._busy = False
        self.client = provisioning.AdbClient(ADB)
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

        self.device_var = tk.StringVar()
        self.device_choice = ttk.Combobox(
            self.status_frame, textvariable=self.device_var, state="readonly", width=38,
        )
        self.device_choice.pack(side="left", fill="x", expand=True)
        ttk.Button(self.status_frame, text="Refresh devices", command=self.check_status).pack(side="left")

        # ---------- buttons ----------
        self.btn_frame = ttk.Frame(self.root)
        self.btn_frame.pack(pady=10)

        ttk.Button(self.btn_frame, text="🔒  Setup Kiosk",
                   command=self.setup_kiosk, width=20).pack(side="left", padx=5)
        ttk.Button(self.btn_frame, text="🔓  Exit Kiosk",
                   command=self.exit_kiosk, width=20).pack(side="left", padx=5)
        ttk.Button(self.btn_frame, text="📱  Restore Setup Changes",
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

        self.root.after(50, self._drain_events)
        self.check_status()
        self.root.mainloop()

    # ---------- helpers ----------
    def _ui(self, callback, *args):
        self._events.put((callback, args))

    def _drain_events(self):
        try:
            while True:
                callback, args = self._events.get_nowait()
                callback(*args)
        except queue.Empty:
            pass
        self.root.after(50, self._drain_events)

    def log_add(self, text):
        if threading.current_thread() is not threading.main_thread():
            self._ui(self.log_add, text)
            return
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def set_status(self, text, detail="", color="#000"):
        self.status_label.config(text=text, fg=color)
        self.status_details.config(text=detail)

    def run_in_thread(self, target, *args):
        if self._busy:
            self.log_add("An operation is already running. Wait for its result.")
            return
        self._busy = True

        def run():
            try:
                target(*args)
            except Exception as exc:
                self.log_add(f"Operation failed: {exc}")
                self._ui(messagebox.showerror, "Operation Failed", str(exc))
            finally:
                self._ui(self._operation_finished)

        threading.Thread(target=run, daemon=True).start()

    def _operation_finished(self):
        self._busy = False

    def _with_device(self, action, operation):
        serial = self.device_var.get() or None

        def run():
            try:
                device = self.client.select(serial)
                self.log_add(f"{action}: selected tablet {device.serial}")
                operation(device)
            except (provisioning.ProvisioningError, package_policy.PackagePolicyError, OSError) as exc:
                self.log_add(f"{action} failed: {exc}")
                self._ui(self.set_status, action + " failed", str(exc), "#c00")
                self._ui(messagebox.showerror, action + " Failed",
                         str(exc) + "\n\nDevice changes may be partial. Inspect before retrying.")

        self.run_in_thread(run)

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
        def check():
            try:
                rows = self.client.devices()
            except provisioning.ProvisioningError:
                self._ui(self._show_devices, [])
                raise
            self._ui(self._show_devices, rows)
        self.run_in_thread(check)

    def _show_devices(self, rows):
        ready = [row.serial for row in rows if row.state == "device"]
        current = self.device_var.get()
        self.device_choice.configure(values=ready)
        if current not in ready:
            self.device_var.set(ready[0] if len(ready) == 1 else "")
        detail = "; ".join(f"{row.serial}: {row.state}" for row in rows)
        self.set_status(
            "Select a tablet" if len(ready) > 1 else ("Tablet connected" if ready else "No authorized tablet"),
            detail or "Connect USB and accept the debugging prompt.",
        )

    def setup_kiosk(self):
        def run(device):
            provisioning.setup(device, APK, PACKAGE_STATE, self.log_add)
            self._ui(self.set_status, "Setup verified", device.serial, "#1a7a1a")
            self._ui(messagebox.showinfo, "Setup Complete",
                     f"Owner, Home, required apps and active managed lock task verified on {device.serial}.")
        self._with_device("Setup", run)

    def exit_kiosk(self):
        def run(device):
            provisioning.exit_kiosk(device)
            self.log_add(f"Lock task exit verified on {device.serial}. Device-owner policy remains installed.")
            self._ui(messagebox.showinfo, "Kiosk Exited",
                     f"Lock task is inactive on {device.serial}. Device-owner policy remains installed.")
        self._with_device("Exit", run)

    def restore_all_apps(self):
        if self._busy:
            return
        if not messagebox.askyesno(
            "Restore Setup Changes",
            "Restore only optional apps changed by this tool on the selected tablet? "
            "Apps already disabled before setup remain disabled.",
        ):
            return

        def run(device):
            device.require_primary_user()
            result = package_policy.restore_package_policy(device.run, PACKAGE_STATE, device.serial)
            if result.failures:
                raise provisioning.ProvisioningError("Restoration failed: " + ", ".join(result.failures))
            self.log_add(f"Restored {len(result.changed)} setup change(s) on {device.serial}.")
            self._ui(messagebox.showinfo, "Setup Changes Restored",
                     f"Restored {len(result.changed)} setup change(s) on {device.serial}.")
        self._with_device("Restore", run)

    def setup_remote_mgmt(self):
        """Guide user through Android Management API enrollment."""
        if self._busy:
            return
        serial = self.device_var.get()
        if not serial:
            messagebox.showerror("Select Tablet", "Select the target serial before enrollment.")
            return
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

        self.log_add("Enrollment token received.")

        # Step 4: factory reset the tablet
        if not messagebox.askyesno(
            "Factory Reset Required",
            f"Tablet {serial} must be factory reset to enroll\n"
            "in Android Management API.\n\n"
            "This will erase ALL data on the tablet.\n\n"
            "A QR code will be displayed on this screen\n"
            "for the tablet to scan during setup.\n\n"
            "Continue with factory reset?",
            icon="warning"):
            self.log_add("Remote setup cancelled.")
            return

        def enroll(device):
            device.run(["shell", "recovery", "--wipe_data"])
            self.log_add(f"Reset request accepted on {device.serial}; completion is unconfirmed.")
            self._ui(self.show_enrollment_qr, token)
        self._with_device("Enrollment reset", enroll)

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
        if self._busy:
            return
        serial = self.device_var.get()
        if not serial:
            messagebox.showerror("Select Tablet", "Select and verify the target serial before requesting a reset.")
            return
        if not messagebox.askyesno(
            "Factory Reset", f"Permanently erase ALL data on tablet {serial}? This cannot be undone.",
            icon="warning",
        ):
            return
        if not messagebox.askyesno("Final Warning", f"Erase tablet {serial} now?", icon="error"):
            return

        def reset(device):
            device.run(["shell", "recovery", "--wipe_data"])
            self.log_add(f"Reset request accepted on {device.serial}; completion is unconfirmed.")
            self._ui(messagebox.showinfo, "Reset Requested",
                     f"Request accepted on {device.serial}. Verify completion on the tablet.")
        self._with_device("Reset", reset)


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

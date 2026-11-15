"""PDFDrop: offline PDF toolkit and editor for Windows 10/11.

    pythonw main.py [file.pdf]           open the editor (several PDFs: open Merge)
    python  main.py --uninstall [--quiet]
"""
import os
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import core  # noqa: E402

PORT = 47614
AUTH = b"PDFDrop-local"


def forward_to_running(paths):
    from multiprocessing.connection import Client
    try:
        with Client(("127.0.0.1", PORT), authkey=AUTH) as c:
            c.send({"paths": paths})
        return True
    except Exception:
        return False


def listen(callback):
    from multiprocessing.connection import Listener
    try:
        lst = Listener(("127.0.0.1", PORT), authkey=AUTH)
    except OSError:
        return None

    def loop():
        while True:
            try:
                with lst.accept() as c:
                    callback(c.recv())
            except Exception:
                time.sleep(0.2)

    threading.Thread(target=loop, daemon=True).start()
    return lst


TOOL_CARDS = [
    ("edit", "Edit a PDF", "Add text, highlight, draw, sign, white-out, fill forms"),
    ("merge", "Merge", "Combine PDFs and images into one PDF"),
    ("split", "Split / extract", "Pull out pages or split into several files"),
    ("compress", "Compress", "Make a PDF much smaller to email or upload"),
    ("rotate", "Rotate pages", "Turn some or all pages the right way"),
    ("img2pdf", "Images → PDF", "Turn photos and scans into one PDF"),
    ("pdf2img", "PDF → images", "Save pages as JPG or PNG pictures"),
    ("protect", "Add password", "Lock a PDF so only you can open it"),
    ("unlock", "Remove password", "Save an unlocked copy of your PDF"),
    ("numbers", "Page numbers", "Add page numbers to every page"),
    ("watermark", "Watermark", "Stamp text like DRAFT or CONFIDENTIAL"),
]
CARD_COLORS = {"edit": "#e8f0fe", "merge": "#e6f4ea", "split": "#fef7e0", "compress": "#fce8e6",
               "rotate": "#f3e8fd", "img2pdf": "#e0f7fa", "pdf2img": "#fff3e0", "protect": "#eceff1",
               "unlock": "#eceff1", "numbers": "#f1f8e9", "watermark": "#fde7f3"}


class App:
    def __init__(self, files):
        import tkinter as tk
        from tkinter import ttk
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            self.root = TkinterDnD.Tk()
            self.dnd = DND_FILES
        except Exception:
            self.root = tk.Tk()
            self.dnd = None
        self.tk, self.ttk = tk, ttk
        self.settings = core.load_settings()
        import storeapi
        self.storeapi = storeapi
        self.lic = storeapi.LicenseWatcher()
        r = self.root
        self.k = k = max(1.0, r.winfo_fpixels("1i") / 96.0)
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        W, H = min(int(1180 * k), int(sw * .92)), min(int(800 * k), int(sh * .88))
        r.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 2 - int(20 * k))}")
        r.minsize(int(860 * k), int(560 * k))
        r.title(core.APP_NAME)
        try:
            r.iconbitmap(os.path.join(HERE, "app.ico"))
        except Exception:
            pass
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
        style.configure("H2.TLabel", font=("Segoe UI Semibold", 11))
        style.configure("Sub.TLabel", foreground="#555", font=("Segoe UI", 10))
        style.configure("Big.TButton", font=("Segoe UI Semibold", 11), padding=(18, 6))

        self.banner = tk.Frame(r, bg="#fff4d6")
        self.banner_label = tk.Label(self.banner, bg="#fff4d6", fg="#6b4e00", font=("Segoe UI", 10))
        self.banner_label.pack(side="left", padx=12, pady=6)
        ttk.Button(self.banner, text="Buy PDFDrop", command=storeapi.open_store_page).pack(side="right", padx=10, pady=4)

        self.home = self._build_home()
        import editor
        self.editor = editor.Editor(r, self)
        self.show_home()
        r.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.dnd:
            r.drop_target_register(self.dnd)
            r.dnd_bind("<<Drop>>", lambda e: self.open_paths(r.tk.splitlist(e.data)))
        if files:
            r.after(150, lambda: self.open_paths(files))
        r.after(400, self._check_license)
        if os.environ.get("PD_SHOT"):  # "path.png;seconds" -> screenshot of the window (tests, store images)
            path, _, secs = os.environ["PD_SHOT"].partition(";")
            r.after(int(float(secs or 3) * 1000), lambda: self._shot(path))

    def _shot(self, path):
        from PIL import ImageGrab
        self.root.update()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        ImageGrab.grab((x, y, x + self.root.winfo_width(), y + self.root.winfo_height()), all_screens=True).save(path)
        if os.environ.get("PD_SHOT_EXIT"):
            self.root.destroy()

    # ---------------------------------------------------------------- home
    def _build_home(self):
        tk, ttk = self.tk, self.ttk
        k = self.k
        f = ttk.Frame(self.root, padding=(int(24 * k), int(18 * k)))
        head = ttk.Frame(f)
        head.pack(fill="x")
        ttk.Label(head, text="PDFDrop", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="   Edit, merge, split and compress PDFs, all offline", style="Sub.TLabel").pack(
            side="left", pady=(8, 0))
        ttk.Button(head, text="Open a PDF…", style="Big.TButton", command=self.open_dialog).pack(side="right")

        grid = ttk.Frame(f)
        grid.pack(fill="x", pady=(int(16 * k), 0))
        cols = 4
        for i, (key, title, sub) in enumerate(TOOL_CARDS):
            bg = CARD_COLORS[key]
            card = tk.Frame(grid, bg=bg, cursor="hand2", highlightthickness=1, highlightbackground="#d6d9e0")
            card.grid(row=i // cols, column=i % cols, sticky="nsew", padx=int(6 * k), pady=int(6 * k))
            t = tk.Label(card, text=title, bg=bg, font=("Segoe UI Semibold", 12), anchor="w")
            t.pack(fill="x", padx=int(14 * k), pady=(int(12 * k), 0))
            s = tk.Label(card, text=sub, bg=bg, fg="#4a4f5c", font=("Segoe UI", 9), anchor="w", justify="left",
                         wraplength=int(220 * k))
            s.pack(fill="x", padx=int(14 * k), pady=(int(2 * k), int(14 * k)))
            for w in (card, t, s):
                w.bind("<Button-1>", lambda e, key=key: self.run_tool(key))
                w.bind("<Enter>", lambda e, c=card: c.configure(highlightbackground="#1a73e8"))
                w.bind("<Leave>", lambda e, c=card: c.configure(highlightbackground="#d6d9e0"))
        for c in range(cols):
            grid.columnconfigure(c, weight=1, uniform="cards")

        drop = tk.Label(f, text="Drop a PDF here to edit it  ·  drop several to merge them", bg="#f3f4f8",
                        fg="#556", font=("Segoe UI", 11), relief="groove", bd=2, height=2)
        drop.pack(fill="x", pady=(int(16 * k), int(8 * k)))
        drop.bind("<Button-1>", lambda e: self.open_dialog())
        ttk.Label(f, text="Recent", style="H2.TLabel").pack(anchor="w", pady=(int(8 * k), int(4 * k)))
        self.recent_box = ttk.Frame(f)
        self.recent_box.pack(fill="x")
        return f

    def _fill_recent(self):
        for w in self.recent_box.winfo_children():
            w.destroy()
        recent = [p for p in self.settings.get("recent", []) if os.path.exists(p)]
        if not recent:
            self.ttk.Label(self.recent_box, text="PDFs you open will appear here.", style="Sub.TLabel").pack(anchor="w")
        for p in recent[:6]:
            lb = self.tk.Label(self.recent_box, text=f"📄  {os.path.basename(p)}   ", fg="#1a4fb8", cursor="hand2",
                               font=("Segoe UI", 10), anchor="w")
            lb.pack(anchor="w")
            self.tk.Label(self.recent_box, text=os.path.dirname(p), fg="#889", font=("Segoe UI", 8)).pack(
                anchor="w", padx=(24, 0))
            lb.bind("<Button-1>", lambda e, p=p: self.open_paths([p]))

    def show_home(self):
        self.editor.pack_forget()
        self._fill_recent()
        self.home.pack(fill="both", expand=True)
        self.root.title(core.APP_NAME)

    def show_editor(self):
        self.home.pack_forget()
        self.editor.pack(fill="both", expand=True)

    # ---------------------------------------------------------------- opening
    def open_dialog(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title="Open a PDF", initialdir=self.settings.get("last_dir") or None,
                                       filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if p:
            self.open_paths([p])

    def open_paths(self, paths):
        paths = [p for p in paths if os.path.isfile(p)]
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if not paths:
            return
        if len(paths) > 1:
            self.run_tool("merge", paths)
            return
        p = paths[0]
        import pdfops
        if os.path.splitext(p)[1].lower() in pdfops.IMAGE_EXT:
            self.run_tool("img2pdf", paths)
            return
        if not self._licensed():
            return
        try:
            if self.editor.load(p):
                self.show_editor()
        except Exception as e:
            traceback.print_exc()
            from tkinter import messagebox
            messagebox.showerror(core.APP_NAME, f"Couldn't open {os.path.basename(p)}:\n{e}")

    def run_tool(self, key, files=None):
        if key == "edit":
            self.open_dialog()
            return
        if not self._licensed():
            return
        import tools
        tools.open_tool(self, key, files or [])

    # ---------------------------------------------------------------- licence
    def _licensed(self):
        lic = self.lic.refresh(force=True)
        self._show_banner(lic)
        if lic.locked:
            from tkinter import messagebox
            messagebox.showinfo(core.APP_NAME, "Your free trial has ended. Buy PDFDrop in the Microsoft Store to keep "
                                               "using it.")
            self.storeapi.open_store_page()
            return False
        return True

    def _check_license(self):
        self._show_banner(self.lic.refresh())
        self.root.after(60_000, self._check_license)

    def _show_banner(self, lic):
        if lic.state == "trial":
            d = lic.days_left
            self.banner_label.configure(text=f"Free trial: {d} day{'s' if d != 1 else ''} left.")
        elif lic.state == "expired":
            self.banner_label.configure(text="Your free trial has ended. Buy PDFDrop to keep using it.")
        if lic.state in ("trial", "expired"):
            if not self.banner.winfo_ismapped():
                self.banner.pack(fill="x", side="top", before=self.home if self.home.winfo_ismapped() else self.editor)
        elif self.banner.winfo_ismapped():
            self.banner.pack_forget()

    def receive(self, msg):
        self.root.after(0, lambda: self.open_paths(msg.get("paths") or []))

    def on_close(self):
        if self.editor.doc is not None and not self.editor.confirm_discard():
            return
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def first_run_setup():
    if core.PACKAGED or not core.DIRECT:
        return
    marker = os.path.join(core.APPDATA_DIR, "installed-" + os.path.normcase(HERE).replace(":", "").replace("\\", "_"))
    if os.path.exists(marker):
        return
    try:
        import wininteg
        wininteg.set_explorer_menu(True)
        wininteg.install_shortcuts()
        os.makedirs(core.APPDATA_DIR, exist_ok=True)
        open(marker, "w").close()
    except Exception:
        traceback.print_exc()


def main():
    args = [a for a in sys.argv[1:] if a not in ("-m", "main")]
    flags = {a for a in args if a.startswith("--")}
    files = [a for a in args if not a.startswith("--")]
    if "--uninstall" in flags:
        import wininteg
        wininteg.uninstall()
        if "--quiet" not in flags:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, "PDFDrop's menu entries and shortcuts were removed.", "PDFDrop", 0)
        return
    if core.PACKAGED:
        import storeapi
        shared = storeapi.take_share()
        if shared:
            files = shared
    if forward_to_running(files):
        return
    first_run_setup()
    app = App(files)
    listener = listen(app.receive)
    try:
        app.run()
    finally:
        if listener:
            listener.close()


if __name__ == "__main__":
    if sys.executable.lower().endswith("pythonw.exe"):
        try:
            os.makedirs(core.APPDATA_DIR, exist_ok=True)
            sys.stdout = sys.stderr = open(os.path.join(core.APPDATA_DIR, "log.txt"), "a", encoding="utf-8", buffering=1)
        except OSError:
            pass
    main()

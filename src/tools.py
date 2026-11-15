"""Dialogs for the PDFDrop toolkit (merge, split, compress...). Work runs in a background thread."""
import os
import threading
import tkinter as tk
import traceback
from tkinter import filedialog, messagebox, ttk

import core
import pdfops

PDF_TYPES = [("PDF files", "*.pdf"), ("All files", "*.*")]
IMG_TYPES = [("Pictures", "*.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp"), ("All files", "*.*")]
MIX_TYPES = [("PDFs and pictures", "*.pdf *.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp"), ("All files", "*.*")]

TITLES = {"merge": "Merge PDFs", "split": "Split or extract pages", "compress": "Compress a PDF",
          "rotate": "Rotate pages", "img2pdf": "Images to PDF", "pdf2img": "PDF to images",
          "protect": "Add a password", "unlock": "Remove a password", "numbers": "Add page numbers",
          "watermark": "Add a watermark"}


def open_tool(app, key, files):
    ToolDialog(app, key, files)


class ToolDialog(tk.Toplevel):
    def __init__(self, app, key, files):
        super().__init__(app.root)
        self.app, self.key, self.k = app, key, app.k
        self.title(f"{TITLES[key]} - {core.APP_NAME}")
        self.transient(app.root)
        self.resizable(True, False)
        try:
            self.iconbitmap(os.path.join(os.path.dirname(__file__), "app.ico"))
        except Exception:
            pass
        self.passwords = {}
        self.page_count = 10 ** 6
        self.body = ttk.Frame(self, padding=int(16 * self.k))
        self.body.pack(fill="both", expand=True)
        ttk.Label(self.body, text=TITLES[key], style="Title.TLabel").pack(anchor="w", pady=(0, int(10 * self.k)))
        multi = key in ("merge", "img2pdf")
        self.files = []
        if multi:
            self._file_list(files)
        else:
            self._single_file(files[0] if files else "")
        self.opts = ttk.Frame(self.body)
        self.opts.pack(fill="x", pady=(int(10 * self.k), 0))
        getattr(self, f"_opts_{key}")()
        if key == "split" and self.files:
            self._set_single(self.files[0])  # re-read now that the ranges box exists
        foot = ttk.Frame(self.body)
        foot.pack(fill="x", pady=(int(16 * self.k), 0))
        self.progress = ttk.Progressbar(foot, maximum=1000)
        self.progress.pack(side="left", fill="x", expand=True)
        self.go = ttk.Button(foot, text=self._go_label(), style="Big.TButton", command=self.start)
        self.go.pack(side="left", padx=(10, 0))
        self.result = ttk.Label(self.body, text="", style="Sub.TLabel", wraplength=int(560 * self.k))
        self.result.pack(anchor="w", pady=(int(8 * self.k), 0))
        self.after(50, self._center)
        if app.dnd:
            self.drop_target_register(app.dnd)
            self.dnd_bind("<<Drop>>", lambda e: self.add_files(self.tk.splitlist(e.data)))

    def _center(self):
        self.update_idletasks()
        r = self.app.root
        w, h = max(self.winfo_reqwidth(), int(600 * self.k)), self.winfo_reqheight()
        x = r.winfo_rootx() + (r.winfo_width() - w) // 2
        y = r.winfo_rooty() + max(0, (r.winfo_height() - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.lift()
        self.focus_force()

    def _go_label(self):
        return {"merge": "Merge", "split": "Split", "compress": "Compress", "rotate": "Rotate", "img2pdf": "Create PDF",
                "pdf2img": "Save images", "protect": "Lock PDF", "unlock": "Unlock PDF", "numbers": "Add numbers",
                "watermark": "Add watermark"}[self.key]

    # ---------------------------------------------------------------- file pickers
    def _file_list(self, files):
        f = ttk.Frame(self.body)
        f.pack(fill="x")
        hint = "PDFs and pictures, in order:" if self.key == "merge" else "Pictures, in order (one per page):"
        ttk.Label(f, text=hint).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(4, 0))
        self.lb = tk.Listbox(row, height=7, activestyle="none", selectmode="extended", font=("Segoe UI", 10))
        self.lb.pack(side="left", fill="both", expand=True)
        btns = ttk.Frame(row)
        btns.pack(side="left", padx=(8, 0), fill="y")
        ttk.Button(btns, text="Add…", command=self._add_dialog).pack(fill="x")
        ttk.Button(btns, text="Up", command=lambda: self._move(-1)).pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Down", command=lambda: self._move(1)).pack(fill="x", pady=(2, 0))
        ttk.Button(btns, text="Remove", command=self._remove).pack(fill="x", pady=(6, 0))
        ttk.Label(f, text="Tip: drop files onto this window to add them.", style="Sub.TLabel").pack(anchor="w", pady=(4, 0))
        self.add_files(files)

    def add_files(self, paths):
        for p in paths:
            if not os.path.isfile(p):
                continue
            ext = os.path.splitext(p)[1].lower()
            ok = ext in pdfops.IMAGE_EXT if self.key == "img2pdf" else (ext == ".pdf" or ext in pdfops.IMAGE_EXT)
            if hasattr(self, "lb"):
                if ok:
                    self.files.append(p)
                    self.lb.insert("end", os.path.basename(p))
            elif ok or ext == ".pdf":
                self._set_single(p)

    def _add_dialog(self):
        paths = filedialog.askopenfilenames(parent=self, title="Add files",
                                            filetypes=IMG_TYPES if self.key == "img2pdf" else MIX_TYPES)
        self.add_files(paths)

    def _move(self, d):
        sel = list(self.lb.curselection())
        if len(sel) != 1:
            return
        i, j = sel[0], sel[0] + d
        if 0 <= j < len(self.files):
            self.files[i], self.files[j] = self.files[j], self.files[i]
            self.lb.delete(0, "end")
            for p in self.files:
                self.lb.insert("end", os.path.basename(p))
            self.lb.selection_set(j)

    def _remove(self):
        for i in reversed(self.lb.curselection()):
            del self.files[i]
            self.lb.delete(i)

    def _single_file(self, path):
        f = ttk.Frame(self.body)
        f.pack(fill="x")
        ttk.Label(f, text="PDF:").pack(side="left")
        self.file_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.file_var, state="readonly").pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(f, text="Choose…", command=self._choose_single).pack(side="left")
        self.info = ttk.Label(self.body, text="", style="Sub.TLabel")
        self.info.pack(anchor="w", pady=(4, 0))
        if path:
            self._set_single(path)

    def _choose_single(self):
        p = filedialog.askopenfilename(parent=self, title="Choose a PDF", filetypes=PDF_TYPES,
                                       initialdir=self.app.settings.get("last_dir") or None)
        if p:
            self._set_single(p)

    def _set_single(self, p):
        self.files = [p]
        self.file_var.set(p)
        try:
            pw = self.passwords.get(p)
            if self.key != "unlock":
                pw = pw or self._ask_password_if_needed(p)
                if pw is False:
                    self.files = []
                    self.file_var.set("")
                    return
            info = pdfops.info(p, pw) if (pw or self.key != "unlock") else None
            if info:
                self.info.configure(text=f"{info['pages']} page{'s' if info['pages'] != 1 else ''} · {core.human(info['size'])}")
                self.page_count = n = info["pages"]
                if self.key == "split" and hasattr(self, "ranges"):  # sensible example: first half, second half
                    h = max(1, n // 2)
                    self.ranges.set(f"1-{h}, {h + 1}-{n}" if n > 1 else "1")
            else:
                self.info.configure(text="Enter the PDF's current password below.")
        except pdfops.PasswordNeeded:
            self.info.configure(text="This PDF is password protected.")
        except Exception as e:
            self.info.configure(text=f"Couldn't read this file: {e}")

    def _ask_password_if_needed(self, p):
        import pymupdf
        from tkinter import simpledialog
        try:
            d = pymupdf.open(p)
            needs = d.needs_pass
            d.close()
        except Exception:
            return None
        if not needs:
            return None
        while True:
            pw = simpledialog.askstring(core.APP_NAME, f"{os.path.basename(p)} is protected.\nEnter its password:",
                                        show="•", parent=self)
            if pw is None:
                return False
            try:
                pdfops.info(p, pw)
                self.passwords[p] = pw
                return pw
            except pdfops.PasswordNeeded:
                messagebox.showerror(core.APP_NAME, "That password is not correct.", parent=self)

    # ---------------------------------------------------------------- option panels
    def _row(self, label):
        r = ttk.Frame(self.opts)
        r.pack(fill="x", pady=3)
        ttk.Label(r, text=label, width=16).pack(side="left")
        return r

    def _ranges_row(self, label="Pages", default="all"):
        r = self._row(label)
        self.ranges = tk.StringVar(value=default)
        ttk.Entry(r, textvariable=self.ranges, width=24).pack(side="left")
        ttk.Label(r, text="  e.g. all, or 1-3, 5, 8-", style="Sub.TLabel").pack(side="left")

    def _opts_merge(self):
        ttk.Label(self.opts, text="Pages keep their size. Pictures become one page each.", style="Sub.TLabel").pack(anchor="w")

    def _opts_split(self):
        self.mode = tk.StringVar(value="ranges")
        r = self._row("Mode")
        ttk.Radiobutton(r, text="Extract pages into one PDF", value="extract", variable=self.mode).pack(anchor="w")
        ttk.Radiobutton(r, text="One PDF per page", value="each", variable=self.mode).pack(anchor="w")
        rr = ttk.Frame(r)
        rr.pack(anchor="w")
        ttk.Radiobutton(rr, text="One PDF every", value="every", variable=self.mode).pack(side="left")
        self.every = tk.StringVar(value="2")
        ttk.Spinbox(rr, from_=1, to=999, width=5, textvariable=self.every).pack(side="left", padx=4)
        ttk.Label(rr, text="pages").pack(side="left")
        ttk.Radiobutton(r, text="One PDF per range below", value="ranges", variable=self.mode).pack(anchor="w")
        self._ranges_row("Pages / ranges", "1-3, 4-6")

    def _opts_compress(self):
        self.level = tk.StringVar(value="Balanced")
        r = self._row("Size")
        for name, sub in (("Smallest", "lowest quality images, best for email"),
                          ("Balanced", "good for screens and sharing"),
                          ("High quality", "still prints well")):
            ttk.Radiobutton(r, text=f"{name}  ({sub})", value=name, variable=self.level).pack(anchor="w")

    def _opts_rotate(self):
        self.angle = tk.IntVar(value=90)
        r = self._row("Turn")
        for a, t in ((90, "Right 90°"), (-90, "Left 90°"), (180, "Upside down 180°")):
            ttk.Radiobutton(r, text=t, value=a, variable=self.angle).pack(side="left", padx=(0, 10))
        self._ranges_row()

    def _opts_img2pdf(self):
        self.paper = tk.StringVar(value="A4")
        r = self._row("Page size")
        for v, t in (("A4", "A4"), ("Letter", "Letter"), ("Fit", "Same as picture")):
            ttk.Radiobutton(r, text=t, value=v, variable=self.paper).pack(side="left", padx=(0, 10))

    def _opts_pdf2img(self):
        self.fmt = tk.StringVar(value="jpg")
        r = self._row("Format")
        ttk.Radiobutton(r, text="JPG (smaller)", value="jpg", variable=self.fmt).pack(side="left", padx=(0, 10))
        ttk.Radiobutton(r, text="PNG (sharpest)", value="png", variable=self.fmt).pack(side="left")
        self.dpi = tk.IntVar(value=150)
        r = self._row("Quality")
        for v, t in ((96, "Screen"), (150, "Good"), (300, "Print")):
            ttk.Radiobutton(r, text=t, value=v, variable=self.dpi).pack(side="left", padx=(0, 10))
        self._ranges_row()

    def _opts_protect(self):
        self.pw1, self.pw2 = tk.StringVar(), tk.StringVar()
        r = self._row("Password")
        ttk.Entry(r, textvariable=self.pw1, show="•", width=28).pack(side="left")
        r = self._row("Repeat")
        ttk.Entry(r, textvariable=self.pw2, show="•", width=28).pack(side="left")
        self.allow_print, self.allow_copy = tk.BooleanVar(value=True), tk.BooleanVar(value=False)
        r = self._row("Allow")
        ttk.Checkbutton(r, text="Printing", variable=self.allow_print).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(r, text="Copying text", variable=self.allow_copy).pack(side="left")
        ttk.Label(self.opts, text="Keep the password somewhere safe: nobody, including PDFDrop, can open the file without it.",
                  style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

    def _opts_unlock(self):
        self.pw1 = tk.StringVar()
        r = self._row("Current password")
        ttk.Entry(r, textvariable=self.pw1, show="•", width=28).pack(side="left")
        ttk.Label(self.opts, text="You need the PDF's password. PDFDrop saves an unlocked copy.",
                  style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

    def _opts_numbers(self):
        self.pos = tk.StringVar(value="Bottom center")
        r = self._row("Position")
        ttk.Combobox(r, values=pdfops.POSITIONS, textvariable=self.pos, state="readonly", width=16).pack(side="left")
        self.tmpl = tk.StringVar(value="Page {n} of {total}")
        r = self._row("Style")
        ttk.Combobox(r, values=["{n}", "Page {n}", "Page {n} of {total}", "{n} / {total}", "- {n} -"],
                     textvariable=self.tmpl, width=22).pack(side="left")
        self.start = tk.StringVar(value="1")
        r = self._row("Start at")
        ttk.Spinbox(r, from_=0, to=9999, width=6, textvariable=self.start).pack(side="left")
        self._ranges_row("Number pages")

    def _opts_watermark(self):
        self.wm = tk.StringVar(value="CONFIDENTIAL")
        r = self._row("Text")
        ttk.Combobox(r, values=["CONFIDENTIAL", "DRAFT", "COPY", "SAMPLE", "DO NOT COPY", "PAID"],
                     textvariable=self.wm, width=28).pack(side="left")
        self.opacity = tk.DoubleVar(value=0.22)
        r = self._row("Strength")
        ttk.Scale(r, from_=0.08, to=0.6, variable=self.opacity, length=int(220 * self.k)).pack(side="left")
        self.diag = tk.BooleanVar(value=True)
        r = self._row("")
        ttk.Checkbutton(r, text="Diagonal", variable=self.diag).pack(side="left")
        self.wm_color = tk.StringVar(value="Red")
        ttk.Combobox(r, values=["Red", "Grey", "Blue"], textvariable=self.wm_color, state="readonly",
                     width=8).pack(side="left", padx=10)
        self._ranges_row()

    # ---------------------------------------------------------------- run
    def _default_out(self, suffix, ext=".pdf"):
        src = self.files[0]
        return os.path.join(os.path.dirname(src), os.path.splitext(os.path.basename(src))[0] + suffix + ext)

    def _ask_save(self, suggested):
        return filedialog.asksaveasfilename(parent=self, title="Save as", defaultextension=".pdf",
                                            initialdir=os.path.dirname(suggested),
                                            initialfile=os.path.basename(pdfops.unique_path(suggested)),
                                            filetypes=[("PDF", "*.pdf")])

    def start(self):
        if not self.files:
            messagebox.showinfo(core.APP_NAME, "Add a file first.", parent=self)
            return
        k = self.key
        pw = self.passwords.get(self.files[0])
        try:
            job, out_desc = self._plan(k, pw)
        except ValueError as e:
            messagebox.showerror(core.APP_NAME, str(e), parent=self)
            return
        if job is None:
            return
        self.go.configure(state="disabled")
        self.progress["value"] = 0
        self.result.configure(text="Working…")

        def prog(f):
            self.after(0, lambda: self.progress.configure(value=f * 1000))

        def work():
            try:
                res = job(prog)
                self.after(0, lambda: self._done(res, out_desc))
            except pdfops.PasswordNeeded:
                self.after(0, lambda: self._fail("That password is not correct."))
            except Exception as e:
                traceback.print_exc()
                self.after(0, lambda e=e: self._fail(str(e) or e.__class__.__name__))
        threading.Thread(target=work, daemon=True).start()

    def _plan(self, k, pw):
        f0 = self.files[0]
        if k == "merge":
            if len(self.files) < 2:
                raise ValueError("Add at least two files to merge.")
            out = self._ask_save(os.path.join(os.path.dirname(f0), "Merged.pdf"))
            pws = dict(self.passwords)
            for p in self.files:
                if p.lower().endswith(".pdf") and p not in pws:
                    got = self._ask_password_if_needed(p)
                    if got is False:
                        return None, None
                    if got:
                        pws[p] = got
            return (lambda prog: pdfops.merge(self.files, out, pws, prog)) if out else None, "file"
        if k == "img2pdf":
            out = self._ask_save(os.path.join(os.path.dirname(f0), "Pictures.pdf"))
            return (lambda prog: pdfops.images_to_pdf(self.files, out, self.paper.get(), prog)) if out else None, "file"
        if k == "split":
            mode = self.mode.get()
            if mode == "extract":
                pdfops.parse_ranges(self.ranges.get(), self.page_count)
                out = self._ask_save(self._default_out(" (extract)"))
                return (lambda prog: pdfops.extract(f0, self.ranges.get(), out, pw)) if out else None, "file"
            if mode == "ranges":
                for part in self.ranges.get().split(","):
                    if part.strip():
                        pdfops.parse_ranges(part, self.page_count)
            out_dir = os.path.join(os.path.dirname(f0), os.path.splitext(os.path.basename(f0))[0] + " (split)")
            every = int(self.every.get() or 1)
            return (lambda prog: pdfops.split(f0, out_dir, mode, every, self.ranges.get(), pw, prog)), "folder"
        if k == "compress":
            out = self._ask_save(self._default_out(" (small)"))
            return (lambda prog: pdfops.compress(f0, out, self.level.get(), pw)) if out else None, "compress"
        if k == "rotate":
            pdfops.parse_ranges(self.ranges.get(), self.page_count)
            out = self._ask_save(self._default_out(" (rotated)"))
            return (lambda prog: pdfops.rotate(f0, out, self.angle.get(), self.ranges.get(), pw)) if out else None, "file"
        if k == "pdf2img":
            pdfops.parse_ranges(self.ranges.get(), self.page_count)
            out_dir = os.path.join(os.path.dirname(f0), os.path.splitext(os.path.basename(f0))[0] + " (images)")
            return (lambda prog: pdfops.pdf_to_images(f0, out_dir, self.dpi.get(), self.fmt.get(), self.ranges.get(),
                                                      pw, prog)), "folder"
        if k == "protect":
            if not self.pw1.get():
                raise ValueError("Type a password.")
            if self.pw1.get() != self.pw2.get():
                raise ValueError("The two passwords don't match.")
            out = self._ask_save(self._default_out(" (locked)"))
            return (lambda prog: pdfops.protect(f0, out, self.pw1.get(), allow_print=self.allow_print.get(),
                                                allow_copy=self.allow_copy.get(), password=pw)) if out else None, "file"
        if k == "unlock":
            if not self.pw1.get():
                raise ValueError("Type the PDF's current password.")
            out = self._ask_save(self._default_out(" (unlocked)"))
            return (lambda prog: pdfops.unlock(f0, out, self.pw1.get())) if out else None, "file"
        if k == "numbers":
            pdfops.parse_ranges(self.ranges.get(), self.page_count)
            out = self._ask_save(self._default_out(" (numbered)"))
            start = int(self.start.get() or 1)
            return (lambda prog: pdfops.page_numbers(f0, out, self.pos.get(), start, self.tmpl.get(),
                                                     ranges=self.ranges.get(), password=pw)) if out else None, "file"
        if k == "watermark":
            if not self.wm.get().strip():
                raise ValueError("Type the watermark text.")
            pdfops.parse_ranges(self.ranges.get(), self.page_count)
            out = self._ask_save(self._default_out(" (watermarked)"))
            color = {"Red": (0.8, 0.1, 0.1), "Grey": (0.35, 0.35, 0.35), "Blue": (0.1, 0.3, 0.75)}[self.wm_color.get()]
            return (lambda prog: pdfops.watermark(f0, out, self.wm.get().strip(), self.opacity.get(), color,
                                                  self.diag.get(), self.ranges.get(), pw)) if out else None, "file"
        raise ValueError("Unknown tool")

    def _done(self, res, kind):
        self.go.configure(state="normal")
        self.progress["value"] = 1000
        target = res[0] if isinstance(res, list) else res
        self.last = target
        if kind == "folder":
            msg = f"Done: {len(res)} file{'s' if len(res) != 1 else ''} in {os.path.dirname(target)}"
        elif kind == "compress":
            before, after = os.path.getsize(self.files[0]), os.path.getsize(res)
            pct = (1 - after / before) * 100 if before else 0
            msg = (f"Done: {core.human(before)} → {core.human(after)} ({pct:.0f}% smaller)" if pct > 1 else
                   f"Done: {core.human(after)}. This PDF was already well compressed.")
        else:
            msg = f"Done: {os.path.basename(res)}"
        self.result.configure(text=msg)
        for w in getattr(self, "_after_btns", []):
            w.destroy()
        row = ttk.Frame(self.body)
        row.pack(anchor="w", pady=(6, 0))
        self._after_btns = [row]
        ttk.Button(row, text="Show in folder", command=lambda: os.system(f'explorer /select,"{target}"')).pack(side="left")
        if str(target).lower().endswith(".pdf"):
            ttk.Button(row, text="Open in editor",
                       command=lambda: (self.destroy(), self.app.open_paths([target]))).pack(side="left", padx=6)
        self._center()

    def _fail(self, msg):
        self.go.configure(state="normal")
        self.progress["value"] = 0
        self.result.configure(text="")
        messagebox.showerror(core.APP_NAME, msg, parent=self)

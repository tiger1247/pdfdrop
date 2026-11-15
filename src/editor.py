"""PDFDrop editor: view pages, annotate, fill forms, rearrange pages.

Additions (text, highlights, ink, white-out, images) are kept as editable objects on top of the
pages and are written into the PDF when saving. Page operations change the document directly.
All object coordinates are in *visible page points* (what the reader sees, rotation applied).
"""
import base64
import copy
import io
import os
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

import pymupdf
from PIL import Image, ImageDraw, ImageTk

import core
import pdfops

TOOLS = [("select", "Select"), ("text", "Text"), ("hl", "Highlight"), ("ink", "Draw"),
         ("white", "White-out"), ("image", "Image"), ("sign", "Sign")]
HL_COLOR = "#ffd84d"
THUMB_W = 120


class Editor(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.settings = app.settings
        self.k = app.k
        self.doc = None
        self.path = None
        self.password = None
        self.objs = []          # per page: list of overlay dicts
        self.page = 0
        self.zoom = 1.0
        self.fit = True
        self.tool = "select"
        self.sel = None         # selected overlay dict
        self.undo_stack, self.redo_stack = [], []
        self.dirty = False
        self._imgs = {}         # keep PhotoImage refs alive
        self._thumbs = []
        self._drag = None
        self._edit_widget = None
        self._build()

    # ---------------------------------------------------------------- layout
    def _build(self):
        px = lambda v: int(v * self.k)  # noqa: E731
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x")
        ttk.Button(bar, text="◀ Tools", command=self.app.show_home).pack(side="left")
        ttk.Button(bar, text="Open…", command=self.app.open_dialog).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Save", command=self.save).pack(side="left", padx=(4, 0))
        ttk.Button(bar, text="Save as…", command=lambda: self.save(ask=True)).pack(side="left", padx=(4, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        self.tool_var = tk.StringVar(value="select")
        for key, label in TOOLS:
            ttk.Radiobutton(bar, text=label, value=key, variable=self.tool_var, style="Toolbutton",
                            command=lambda k=key: self.set_tool(k)).pack(side="left", padx=1)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        self.color_btn = tk.Button(bar, width=2, relief="groove", command=self.pick_color,
                                   bg=self.settings.get("pen_color", "#d32f2f"))
        self.color_btn.pack(side="left")
        self.size_var = tk.StringVar(value=str(self.settings.get("text_size", 14)))
        self.size_box = ttk.Spinbox(bar, from_=1, to=96, width=4, textvariable=self.size_var,
                                    command=self._size_changed)
        self.size_box.pack(side="left", padx=(4, 0))
        self.size_box.bind("<Return>", lambda e: self._size_changed())
        self.size_label = ttk.Label(bar, text="pt")
        self.size_label.pack(side="left", padx=(2, 0))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="↶", width=3, command=self.undo).pack(side="left")
        ttk.Button(bar, text="↷", width=3, command=self.redo).pack(side="left", padx=(2, 0))
        ttk.Button(bar, text="Fit", width=4, command=self.zoom_fit).pack(side="right")
        ttk.Button(bar, text="+", width=3, command=lambda: self.set_zoom(self.zoom * 1.2)).pack(side="right", padx=2)
        ttk.Button(bar, text="−", width=3, command=lambda: self.set_zoom(self.zoom / 1.2)).pack(side="right")
        self.page_label = ttk.Label(bar, text="")
        self.page_label.pack(side="right", padx=10)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        # thumbnails
        side = ttk.Frame(body, padding=(6, 0, 0, 6))
        side.pack(side="left", fill="y")
        tw = px(THUMB_W + 30)
        self.thumbs = tk.Canvas(side, width=tw, bg="#e9eaef", highlightthickness=0)
        tsb = ttk.Scrollbar(side, orient="vertical", command=self.thumbs.yview)
        self.thumbs.configure(yscrollcommand=tsb.set)
        pbar = ttk.Frame(side)
        pbar.pack(side="bottom", fill="x", pady=(6, 0))
        for txt, cmd in (("⟲", lambda: self.rotate_page(-90)), ("⟳", lambda: self.rotate_page(90)),
                         ("↑", lambda: self.move_page(-1)), ("↓", lambda: self.move_page(1)),
                         ("🗑", self.delete_page), ("+", self.add_pages_menu)):
            ttk.Button(pbar, text=txt, width=3, command=cmd).pack(side="left", padx=1)
        self.thumbs.pack(side="left", fill="y")
        tsb.pack(side="left", fill="y")
        self.thumbs.bind("<Button-1>", self._thumb_click)
        self.thumbs.bind("<MouseWheel>", lambda e: self.thumbs.yview_scroll(-1 * (e.delta // 120), "units"))

        # page canvas
        wrap = ttk.Frame(body)
        wrap.pack(side="left", fill="both", expand=True)
        self.cv = tk.Canvas(wrap, bg="#8a8d99", highlightthickness=0)
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.cv.yview)
        hs = ttk.Scrollbar(wrap, orient="horizontal", command=self.cv.xview)
        self.cv.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side="right", fill="y")
        hs.pack(side="bottom", fill="x")
        self.cv.pack(fill="both", expand=True)
        self.hint = ttk.Label(wrap, text="", style="Sub.TLabel", anchor="w")
        self.cv.bind("<Configure>", lambda e: self.fit and self.doc and self.after_idle(self.zoom_fit))
        self.cv.bind("<ButtonPress-1>", self._down)
        self.cv.bind("<B1-Motion>", self._move)
        self.cv.bind("<ButtonRelease-1>", self._up)
        self.cv.bind("<Double-Button-1>", self._double)
        self.cv.bind("<MouseWheel>", self._wheel)
        self.cv.bind("<Motion>", self._hover)

        self.status = ttk.Label(self, text="", style="Sub.TLabel", padding=(10, 2))
        self.status.pack(fill="x")
        for seq, fn in (("<Control-z>", self.undo), ("<Control-y>", self.redo), ("<Control-s>", self.save),
                        ("<Delete>", self.delete_selected), ("<Next>", lambda: self.goto(self.page + 1)),
                        ("<Prior>", lambda: self.goto(self.page - 1)), ("<Escape>", self._escape)):
            self.app.root.bind(seq, lambda e, f=fn: self._key(e, f))

    def _key(self, event, fn):
        if not self.winfo_ismapped() or isinstance(event.widget, (tk.Text, tk.Entry, ttk.Entry, ttk.Spinbox)):
            return
        fn()

    # ---------------------------------------------------------------- document
    def load(self, path, password=None):
        if not self.confirm_discard():
            return False
        with open(path, "rb") as f:
            data = f.read()
        doc = pymupdf.open(stream=data, filetype=os.path.splitext(path)[1][1:] or "pdf")
        if doc.needs_pass:
            while True:
                pw = password or simpledialog.askstring(core.APP_NAME, f"{os.path.basename(path)} is protected.\n"
                                                        "Enter its password:", show="•", parent=self)
                password = None
                if pw is None:
                    return False
                if doc.authenticate(pw):
                    self.password = pw
                    break
                messagebox.showerror(core.APP_NAME, "That password is not correct.", parent=self)
        else:
            self.password = None
        if not doc.is_pdf:
            doc = pymupdf.open("pdf", doc.convert_to_pdf())
        self.doc, self.path = doc, path
        self.objs = [[] for _ in range(doc.page_count)]
        self.page, self.sel, self.dirty = 0, None, False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.fit = True
        core.add_recent(self.settings, path)
        self._title()
        self.render_thumbs()
        self.after_idle(self.zoom_fit)
        has_forms = any(True for p in doc for _ in p.widgets())
        self.set_status("This PDF has form fields: choose Select and click a field to fill it in." if has_forms
                        else "Tip: choose a tool above, then click or drag on the page.")
        return True

    def _title(self):
        name = os.path.basename(self.path) if self.path else "Untitled"
        self.app.root.title(f"{'• ' if self.dirty else ''}{name} - {core.APP_NAME}")

    def confirm_discard(self):
        if not self.dirty:
            return True
        r = messagebox.askyesnocancel(core.APP_NAME, "Save changes to "
                                      f"{os.path.basename(self.path or 'this PDF')} first?", parent=self)
        if r is None:
            return False
        if r:
            return self.save()
        return True

    def mark(self):
        self.dirty = True
        self._title()

    # ---------------------------------------------------------------- undo
    def push_undo(self, doc_change=False):
        self.undo_stack.append(self._snapshot(doc_change))
        del self.undo_stack[:-40]
        self.redo_stack.clear()

    def _snapshot(self, with_doc):
        return {"doc": self.doc.tobytes() if with_doc else None, "objs": copy.deepcopy(self.objs), "page": self.page}

    def _restore(self, snap):
        if snap["doc"] is not None:
            self.doc = pymupdf.open("pdf", snap["doc"])
            if self.password:
                self.doc.authenticate(self.password)
            self.render_thumbs()
        self.objs = snap["objs"]
        self.sel = None
        self.goto(min(snap["page"], self.doc.page_count - 1))
        self.mark()

    def undo(self):
        if self.doc and self.undo_stack:
            snap = self.undo_stack.pop()
            self.redo_stack.append(self._snapshot(snap["doc"] is not None))
            self._restore(snap)

    def redo(self):
        if self.doc and self.redo_stack:
            snap = self.redo_stack.pop()
            self.undo_stack.append(self._snapshot(snap["doc"] is not None))
            self._restore(snap)

    # ---------------------------------------------------------------- view
    def page_size(self, pno=None):
        r = self.doc[self.page if pno is None else pno].rect
        return r.width, r.height

    def zoom_fit(self):
        if not self.doc:
            return
        self.fit = True
        w, h = self.page_size()
        cw = max(200, self.cv.winfo_width() - 40)
        self.zoom = min(4.0, max(0.2, cw / w))
        self.redraw()

    def set_zoom(self, z):
        if not self.doc:
            return
        self.fit = False
        self.zoom = min(6.0, max(0.15, z))
        self.redraw()

    def goto(self, pno):
        if not self.doc or not (0 <= pno < self.doc.page_count):
            return
        self._commit_text()
        self.page, self.sel = pno, None
        if self.fit:
            self.zoom_fit()
        else:
            self.redraw()
        self.cv.yview_moveto(0)
        self._highlight_thumb()

    def redraw(self):
        cv = self.cv
        cv.delete("all")
        if not self.doc:
            return
        z = self.zoom
        page = self.doc[self.page]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False, annots=True)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        self._imgs["page"] = ImageTk.PhotoImage(img)
        self.ox, self.oy = 20, 20
        cv.create_rectangle(self.ox + 3, self.oy + 3, self.ox + pix.width + 3, self.oy + pix.height + 3,
                            fill="#5c5f6b", outline="")
        cv.create_image(self.ox, self.oy, image=self._imgs["page"], anchor="nw", tags="pageimg")
        cv.configure(scrollregion=(0, 0, pix.width + 40, pix.height + 40))
        for i, o in enumerate(self.objs[self.page]):
            self._draw_obj(o, i)
        if self.sel is not None and self.sel in self.objs[self.page]:
            self._draw_selection(self.sel)
        self.page_label.configure(text=f"Page {self.page + 1} / {self.doc.page_count}   {round(z * 100)}%")

    def to_cv(self, x, y):
        return self.ox + x * self.zoom, self.oy + y * self.zoom

    def to_pdf(self, cx, cy):
        cx, cy = self.cv.canvasx(cx), self.cv.canvasy(cy)
        return (cx - self.ox) / self.zoom, (cy - self.oy) / self.zoom

    def _draw_obj(self, o, idx):
        cv, z, tag = self.cv, self.zoom, f"obj{idx}"
        t = o["type"]
        if t == "text":
            x, y = self.to_cv(o["x"], o["y"])
            cv.create_text(x, y, text=o["text"], anchor="nw", fill=o["color"],
                           font=("Arial", -max(1, round(o["size"] * z))), tags=tag)
        elif t in ("hl", "white"):
            x0, y0 = self.to_cv(*o["rect"][:2])
            x1, y1 = self.to_cv(*o["rect"][2:])
            if t == "white":
                cv.create_rectangle(x0, y0, x1, y1, fill="white", outline="#b0b4c0", dash=(3, 3), tags=tag)
            else:
                w, h = max(1, int(x1 - x0)), max(1, int(y1 - y0))
                rgb = tuple(int(c * 255) for c in core.hex_to_rgb(o["color"]))
                im = Image.new("RGBA", (w, h), rgb + (110,))
                self._imgs[tag] = ImageTk.PhotoImage(im)
                cv.create_image(x0, y0, image=self._imgs[tag], anchor="nw", tags=tag)
        elif t == "ink":
            pts = [c for p in o["points"] for c in self.to_cv(*p)]
            if len(pts) >= 4:
                cv.create_line(*pts, fill=o["color"], width=max(1, o["width"] * z), capstyle="round",
                               joinstyle="round", smooth=True, tags=tag)
        elif t == "image":
            x0, y0 = self.to_cv(*o["rect"][:2])
            x1, y1 = self.to_cv(*o["rect"][2:])
            im = Image.open(io.BytesIO(o["png"])).convert("RGBA")
            im = im.resize((max(1, int(x1 - x0)), max(1, int(y1 - y0))), Image.LANCZOS)
            self._imgs[tag] = ImageTk.PhotoImage(im)
            cv.create_image(x0, y0, image=self._imgs[tag], anchor="nw", tags=tag)

    def obj_bbox(self, o):
        """Bounding box in page points."""
        t = o["type"]
        if t in ("hl", "white", "image"):
            return tuple(o["rect"])
        if t == "ink":
            xs = [p[0] for p in o["points"]]
            ys = [p[1] for p in o["points"]]
            pad = o["width"] / 2 + 2
            return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad
        lines = o["text"].split("\n") or [""]
        w = max(pymupdf.get_text_length(ln, "helv", o["size"]) for ln in lines)
        return o["x"], o["y"], o["x"] + max(w, o["size"]), o["y"] + o["size"] * 1.2 * len(lines)

    def _draw_selection(self, o):
        x0, y0, x1, y1 = self.obj_bbox(o)
        a, b = self.to_cv(x0, y0)
        c, d = self.to_cv(x1, y1)
        self.cv.create_rectangle(a - 3, b - 3, c + 3, d + 3, outline="#1a73e8", dash=(4, 2), tags="sel")
        if o["type"] in ("hl", "white", "image", "text"):
            self.cv.create_rectangle(c - 1, d - 1, c + 9, d + 9, fill="#1a73e8", outline="white", tags="sel")

    # ---------------------------------------------------------------- thumbnails
    def render_thumbs(self):
        tc = self.thumbs
        tc.delete("all")
        self._thumbs = []
        if not self.doc:
            return
        y = 10
        tw = int(THUMB_W * self.k)
        self._thumb_pos = []
        for i, page in enumerate(self.doc):
            z = tw / page.rect.width
            pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
            img = ImageTk.PhotoImage(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            self._thumbs.append(img)
            x = 14
            tc.create_rectangle(x - 4, y - 4, x + pix.width + 4, y + pix.height + 4, outline="", fill="",
                                tags=(f"frame{i}", "frame"))
            tc.create_image(x, y, image=img, anchor="nw", tags=f"t{i}")
            tc.create_text(x + pix.width / 2, y + pix.height + 12, text=str(i + 1), fill="#556",
                           font=("Segoe UI", 9))
            self._thumb_pos.append((y - 6, y + pix.height + 22))
            y += pix.height + 34
        tc.configure(scrollregion=(0, 0, tw + 20, y))
        self._highlight_thumb()

    def _highlight_thumb(self):
        tc = self.thumbs
        tc.itemconfigure("frame", outline="")
        tc.itemconfigure(f"frame{self.page}", outline="#1a73e8", width=3)
        if getattr(self, "_thumb_pos", None) and self.page < len(self._thumb_pos):
            top, bot = self._thumb_pos[self.page]
            total = float(tc.bbox("all")[3]) if tc.bbox("all") else 1
            v0, v1 = tc.yview()
            if top / total < v0 or bot / total > v1:
                tc.yview_moveto(max(0, top / total - 0.02))

    def _thumb_click(self, event):
        y = self.thumbs.canvasy(event.y)
        for i, (a, b) in enumerate(getattr(self, "_thumb_pos", [])):
            if a <= y <= b:
                self.goto(i)
                return

    # ---------------------------------------------------------------- page operations
    def rotate_page(self, angle):
        if not self.doc:
            return
        self._commit_text()
        self.push_undo(doc_change=True)
        p = self.doc[self.page]
        old_w, old_h = p.rect.width, p.rect.height
        p.set_rotation((p.rotation + angle) % 360)
        # keep added objects in place relative to the page content
        self.objs[self.page] = [self._rotate_obj(o, angle, old_w, old_h) for o in self.objs[self.page]]
        self.mark()
        self.render_thumbs()
        self.goto(self.page)

    def _rotate_obj(self, o, angle, w, h):
        def rp(x, y):
            return (h - y, x) if angle == 90 else (y, w - x)
        o = copy.deepcopy(o)
        if o["type"] == "ink":
            o["points"] = [rp(*p) for p in o["points"]]
        elif o["type"] == "text":
            o["x"], o["y"] = rp(o["x"], o["y"])
        else:
            a, b = rp(*o["rect"][:2]), rp(*o["rect"][2:])
            o["rect"] = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        return o

    def move_page(self, delta):
        if not self.doc:
            return
        j = self.page + delta
        if not (0 <= j < self.doc.page_count):
            return
        self._commit_text()
        self.push_undo(doc_change=True)
        order = list(range(self.doc.page_count))
        order[self.page], order[j] = order[j], order[self.page]
        self.doc.select(order)
        self.objs[self.page], self.objs[j] = self.objs[j], self.objs[self.page]
        self.page = j
        self.mark()
        self.render_thumbs()
        self.goto(j)

    def delete_page(self):
        if not self.doc:
            return
        if self.doc.page_count == 1:
            messagebox.showinfo(core.APP_NAME, "A PDF needs at least one page.", parent=self)
            return
        self._commit_text()
        self.push_undo(doc_change=True)
        self.doc.delete_page(self.page)
        del self.objs[self.page]
        self.mark()
        self.render_thumbs()
        self.goto(min(self.page, self.doc.page_count - 1))

    def add_pages_menu(self):
        if not self.doc:
            return
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Blank page after this one", command=self.add_blank)
        m.add_command(label="Pages from a PDF or image…", command=self.add_from_file)
        m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def add_blank(self):
        self._commit_text()
        self.push_undo(doc_change=True)
        w, h = self.page_size()
        self.doc.new_page(self.page + 1, width=w, height=h)
        self.objs.insert(self.page + 1, [])
        self.mark()
        self.render_thumbs()
        self.goto(self.page + 1)

    def add_from_file(self):
        paths = filedialog.askopenfilenames(parent=self, title="Add pages from…", filetypes=[
            ("PDFs and images", "*.pdf *.jpg *.jpeg *.png *.bmp *.gif *.tif *.tiff *.webp"), ("All files", "*.*")])
        if not paths:
            return
        self._commit_text()
        self.push_undo(doc_change=True)
        at = self.page + 1
        added = 0
        for p in paths:
            try:
                if os.path.splitext(p)[1].lower() in pdfops.IMAGE_EXT:
                    src = pdfops._image_doc(p, "Fit")
                else:
                    src = pdfops.open_pdf(p, simpledialog.askstring(core.APP_NAME, "Password:", show="•", parent=self)
                                          if pymupdf.open(p).needs_pass else None)
                self.doc.insert_pdf(src, start_at=at + added)
                for _ in range(src.page_count):
                    self.objs.insert(at + added, [])
                    added += 1
                src.close()
            except Exception as e:
                messagebox.showerror(core.APP_NAME, f"Couldn't add {os.path.basename(p)}:\n{e}", parent=self)
        self.mark()
        self.render_thumbs()
        self.goto(at)

    # ---------------------------------------------------------------- tools
    def set_tool(self, key):
        self._commit_text()
        if key == "sign":
            self.tool_var.set(self.tool)
            self.place_signature()
            return
        if key == "image":
            self.tool_var.set(self.tool)
            self.place_image_file()
            return
        self.tool = key
        self.tool_var.set(key)
        self.sel = None
        cursor = {"select": "arrow", "text": "xterm", "hl": "crosshair", "ink": "pencil", "white": "crosshair"}
        self.cv.configure(cursor=cursor.get(key, "arrow"))
        if key == "text":
            self.size_var.set(str(self.settings.get("text_size", 14)))
            self.size_label.configure(text="pt")
            self._show_color(self.settings.get("text_color", "#111111"))
        elif key == "ink":
            self.size_var.set(str(self.settings.get("pen_width", 2.0)))
            self.size_label.configure(text="px")
            self._show_color(self.settings.get("pen_color", "#d32f2f"))
        elif key == "hl":
            self._show_color(HL_COLOR)
        hints = {"select": "Click an item to select it; drag to move, drag the blue corner to resize, Delete to remove. "
                           "Click a form field to fill it in.",
                 "text": "Click where the text should go and type. Click elsewhere when done.",
                 "hl": "Drag over the area to highlight.",
                 "ink": "Draw with the mouse or pen.",
                 "white": "Drag over anything you want to remove. It is erased from the PDF when you save."}
        self.set_status(hints.get(key, ""))
        if self.doc:
            self.redraw()

    def _show_color(self, c):
        self.color_btn.configure(bg=c, activebackground=c)

    def pick_color(self):
        c = colorchooser.askcolor(color=self.color_btn.cget("bg"), parent=self)[1]
        if not c:
            return
        self._show_color(c)
        key = "text_color" if self.tool == "text" else "pen_color"
        if self.tool in ("text", "ink"):
            self.settings[key] = c
            core.save_settings(self.settings)
        if self.sel is not None and self.sel["type"] in ("text", "ink", "hl"):
            self.push_undo()
            self.sel["color"] = c
            self.mark()
            self.redraw()

    def _size_changed(self):
        try:
            v = float(self.size_var.get())
        except ValueError:
            return
        if self.tool == "ink":
            self.settings["pen_width"] = max(0.5, min(v, 40))
        else:
            self.settings["text_size"] = int(max(4, min(v, 96)))
        core.save_settings(self.settings)
        if self.sel is not None and self.sel["type"] in ("text", "ink"):
            self.push_undo()
            if self.sel["type"] == "text":
                self.sel["size"] = max(4, min(v, 96))
            else:
                self.sel["width"] = max(0.5, min(v, 40))
            self.mark()
            self.redraw()

    def set_status(self, text):
        self.status.configure(text=text)

    # ---------------------------------------------------------------- mouse
    def _hit(self, x, y):
        for o in reversed(self.objs[self.page]):
            x0, y0, x1, y1 = self.obj_bbox(o)
            if x0 - 3 <= x <= x1 + 3 and y0 - 3 <= y <= y1 + 3:
                return o
        return None

    def _on_handle(self, x, y):
        if self.sel is None or self.sel["type"] not in ("hl", "white", "image", "text"):
            return False
        _, _, x1, y1 = self.obj_bbox(self.sel)
        tol = 10 / self.zoom
        return x1 - tol / 3 <= x <= x1 + tol and y1 - tol / 3 <= y <= y1 + tol

    def _widget_at(self, x, y):
        page = self.doc[self.page]
        pt = pymupdf.Point(x, y) * page.derotation_matrix
        for w in page.widgets():
            if pt in w.rect:
                return w
        return None

    def _hover(self, event):
        if not self.doc or self.tool != "select":
            return
        x, y = self.to_pdf(event.x, event.y)
        if self._on_handle(x, y):
            self.cv.configure(cursor="size_nw_se")
        elif self._hit(x, y):
            self.cv.configure(cursor="fleur")
        elif self._widget_at(x, y):
            self.cv.configure(cursor="hand2")
        else:
            self.cv.configure(cursor="arrow")

    def _down(self, event):
        if not self.doc:
            return
        self.cv.focus_set()
        x, y = self.to_pdf(event.x, event.y)
        if self._edit_widget:
            self._commit_text()
            if self.tool == "text":
                return
        t = self.tool
        if t == "select":
            if self._on_handle(x, y):
                self.push_undo()
                self._drag = ("resize", x, y, copy.deepcopy(self.sel))
                return
            o = self._hit(x, y)
            self.sel = o
            if o is not None:
                self.push_undo()
                self._drag = ("move", x, y, copy.deepcopy(o))
            else:
                self._drag = None
                w = self._widget_at(x, y)
                if w is not None:
                    self.fill_field(w)
            self.redraw()
        elif t == "text":
            o = self._hit(x, y)
            if o is not None and o["type"] == "text":
                self.edit_text(o)
            else:
                self.edit_text(None, x, y)
        elif t == "ink":
            self.push_undo()
            o = {"type": "ink", "points": [(x, y)], "color": self.color_btn.cget("bg"),
                 "width": float(self.settings.get("pen_width", 2.0))}
            self.objs[self.page].append(o)
            self._drag = ("ink", o)
            self._ink_last = self.to_cv(x, y)
        elif t in ("hl", "white"):
            self._drag = ("rect", x, y)
            a, b = self.to_cv(x, y)
            self.cv.create_rectangle(a, b, a, b, outline="#1a73e8", dash=(3, 3), tags="rubber",
                                     fill=HL_COLOR if t == "hl" else "white", stipple="gray50" if t == "hl" else "")

    def _move(self, event):
        if not self._drag:
            return
        x, y = self.to_pdf(event.x, event.y)
        kind = self._drag[0]
        if kind == "ink":
            o = self._drag[1]
            o["points"].append((x, y))
            a, b = self._ink_last
            c, d = self.to_cv(x, y)
            self.cv.create_line(a, b, c, d, fill=o["color"], width=max(1, o["width"] * self.zoom),
                                capstyle="round")
            self._ink_last = (c, d)
        elif kind == "rect":
            _, x0, y0 = self._drag
            a, b = self.to_cv(x0, y0)
            c, d = self.to_cv(x, y)
            self.cv.coords("rubber", a, b, c, d)
        elif kind == "move":
            _, sx, sy, orig = self._drag
            dx, dy = x - sx, y - sy
            o = self.sel
            if o["type"] == "text":
                o["x"], o["y"] = orig["x"] + dx, orig["y"] + dy
            elif o["type"] == "ink":
                o["points"] = [(px + dx, py + dy) for px, py in orig["points"]]
            else:
                r = orig["rect"]
                o["rect"] = (r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy)
            self.redraw()
        elif kind == "resize":
            _, sx, sy, orig = self._drag
            o = self.sel
            if o["type"] == "text":
                x0, y0, x1, y1 = self.obj_bbox(orig)
                scale = max(0.2, (y - y0) / max(1, y1 - y0))
                o["size"] = max(4, min(96, orig["size"] * scale))
            else:
                r = orig["rect"]
                nx1, ny1 = max(r[0] + 4, x), max(r[1] + 4, y)
                if o["type"] == "image":  # keep the picture's proportions
                    ratio = (r[3] - r[1]) / max(1e-6, r[2] - r[0])
                    ny1 = r[1] + (nx1 - r[0]) * ratio
                o["rect"] = (r[0], r[1], nx1, ny1)
            self.redraw()

    def _up(self, event):
        if not self._drag:
            return
        kind = self._drag[0]
        x, y = self.to_pdf(event.x, event.y)
        if kind == "ink":
            o = self._drag[1]
            if len(o["points"]) < 2:
                o["points"].append((o["points"][0][0] + 0.5, o["points"][0][1] + 0.5))
            self.mark()
            self.redraw()
        elif kind == "rect":
            _, x0, y0 = self._drag
            self.cv.delete("rubber")
            r = (min(x0, x), min(y0, y), max(x0, x), max(y0, y))
            if r[2] - r[0] > 2 and r[3] - r[1] > 2:
                self.push_undo()
                o = {"type": self.tool, "rect": r, "color": HL_COLOR}
                self.objs[self.page].append(o)
                self.mark()
                self.redraw()
        elif kind in ("move", "resize"):
            orig = self._drag[3]
            if self.sel == orig and self.undo_stack:
                self.undo_stack.pop()  # a click without moving: nothing to undo
            else:
                self.mark()
        self._drag = None

    def _double(self, event):
        """Tk delivers a quick second press as a double-click instead of a press, so treat it as both."""
        if not self.doc:
            return
        x, y = self.to_pdf(event.x, event.y)
        o = self._hit(x, y)
        if o is not None and o["type"] == "text" and self.tool in ("select", "text"):
            self._drag = None
            self.edit_text(o)
            return
        self._down(event)

    def _wheel(self, event):
        if event.state & 0x0004:  # Ctrl: zoom
            self.set_zoom(self.zoom * (1.1 if event.delta > 0 else 1 / 1.1))
            return
        first, last = self.cv.yview()
        if event.delta < 0 and last >= 0.999 and self.page < self.doc.page_count - 1 if self.doc else False:
            self.goto(self.page + 1)
            return
        if event.delta > 0 and first <= 0.001 and self.page > 0 if self.doc else False:
            self.goto(self.page - 1)
            self.cv.yview_moveto(1)
            return
        self.cv.yview_scroll(-1 * (event.delta // 120), "units")

    def _escape(self):
        if self._edit_widget:
            self._commit_text()
        self.sel = None
        if self.doc:
            self.redraw()

    def delete_selected(self):
        if self.sel is not None and self.sel in self.objs[self.page]:
            self.push_undo()
            self.objs[self.page].remove(self.sel)
            self.sel = None
            self.mark()
            self.redraw()

    # ---------------------------------------------------------------- text
    def edit_text(self, obj, x=None, y=None):
        self._commit_text()
        if obj is None:
            obj = {"type": "text", "x": x, "y": y, "text": "", "color": self.settings.get("text_color", "#111111"),
                   "size": float(self.settings.get("text_size", 14))}
            new = True
        else:
            new = False
        size = max(6, round(obj["size"] * self.zoom))
        t = tk.Text(self.cv, font=("Arial", -size), fg=obj["color"], bd=1, relief="solid", wrap="none",
                    width=max(12, max((len(s) for s in obj["text"].split("\n")), default=0) + 2),
                    height=max(1, obj["text"].count("\n") + 1), undo=True, highlightthickness=0, padx=0, pady=0)
        t.insert("1.0", obj["text"])
        cx, cy = self.to_cv(obj["x"], obj["y"])
        win = self.cv.create_window(cx, cy, window=t, anchor="nw", tags="editor")
        t.focus_set()

        def grow(_e=None):
            lines = t.get("1.0", "end-1c").split("\n")
            t.configure(width=max(12, max(len(s) for s in lines) + 2), height=max(1, len(lines)))
        t.bind("<KeyRelease>", grow)
        t.bind("<Escape>", lambda e: (self._commit_text(), "break")[1])
        t.bind("<Control-Return>", lambda e: (self._commit_text(), "break")[1])
        if not new:
            self.cv.itemconfigure(f"obj{self.objs[self.page].index(obj)}", state="hidden")
        self._edit_widget = (t, win, obj, new)

    def _commit_text(self):
        if not self._edit_widget:
            return
        t, win, obj, new = self._edit_widget
        self._edit_widget = None
        text = t.get("1.0", "end-1c").rstrip()
        self.cv.delete(win)
        t.destroy()
        if new and text:
            self.push_undo()
            obj["text"] = text
            self.objs[self.page].append(obj)
            self.mark()
        elif not new and text != obj["text"]:
            self.push_undo()
            if text:
                obj["text"] = text
            else:
                self.objs[self.page].remove(obj)
            self.mark()
        if self.doc:
            self.redraw()

    # ---------------------------------------------------------------- images & signatures
    def place_image_file(self):
        if not self.doc:
            return
        p = filedialog.askopenfilename(parent=self, title="Insert a picture", filetypes=[
            ("Pictures", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"), ("All files", "*.*")])
        if not p:
            return
        try:
            from PIL import ImageOps
            with Image.open(p) as im:
                im = ImageOps.exif_transpose(im).convert("RGBA")
                im.thumbnail((2400, 2400))
                buf = io.BytesIO()
                im.save(buf, "PNG")
            self._add_image(buf.getvalue(), im.size)
        except Exception as e:
            messagebox.showerror(core.APP_NAME, f"Couldn't open that picture:\n{e}", parent=self)

    def _add_image(self, png, size, width_pt=None):
        pw, ph = self.page_size()
        w = width_pt or min(pw * 0.5, 240)
        h = w * size[1] / max(1, size[0])
        # centre of the visible part of the page
        vx = (self.cv.canvasx(self.cv.winfo_width() / 2) - self.ox) / self.zoom
        vy = (self.cv.canvasy(self.cv.winfo_height() / 2) - self.oy) / self.zoom
        x0 = min(max(0, vx - w / 2), pw - w)
        y0 = min(max(0, vy - h / 2), ph - h)
        self.push_undo()
        o = {"type": "image", "rect": (x0, y0, x0 + w, y0 + h), "png": png}
        self.objs[self.page].append(o)
        self.sel = o
        self.tool = "select"
        self.tool_var.set("select")
        self.mark()
        self.redraw()
        self.set_status("Drag the picture into place; drag its blue corner to resize.")

    def place_signature(self):
        if not self.doc:
            return
        saved = self.settings.get("signature")
        if saved:
            m = tk.Menu(self, tearoff=0)
            m.add_command(label="Use my saved signature", command=lambda: self._use_signature(base64.b64decode(saved)))
            m.add_command(label="Draw a new signature…", command=self._draw_signature)
            m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        else:
            self._draw_signature()

    def _use_signature(self, png):
        size = Image.open(io.BytesIO(png)).size
        self._add_image(png, size, width_pt=150)

    def _draw_signature(self):
        SignaturePad(self, self._signature_done)

    def _signature_done(self, png, remember):
        if remember:
            self.settings["signature"] = base64.b64encode(png).decode()
            core.save_settings(self.settings)
        self._use_signature(png)

    # ---------------------------------------------------------------- forms
    def fill_field(self, w):
        name = w.field_label or w.field_name or "Field"
        ft = w.field_type
        try:
            if ft == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                new = not bool(w.field_value) or w.field_value in ("Off", False)
                self.push_undo(doc_change=True)
                w.field_value = w.on_state() if new else "Off"
            elif ft == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                self.push_undo(doc_change=True)
                w.field_value = w.on_state()
            elif ft in (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, pymupdf.PDF_WIDGET_TYPE_LISTBOX):
                choices = [c if isinstance(c, str) else c[0] for c in (w.choice_values or [])]
                val = ChoiceDialog.ask(self, name, choices, w.field_value)
                if val is None:
                    return
                self.push_undo(doc_change=True)
                w.field_value = val
            elif ft == pymupdf.PDF_WIDGET_TYPE_TEXT:
                val = simpledialog.askstring(core.APP_NAME, name, initialvalue=w.field_value or "", parent=self)
                if val is None:
                    return
                self.push_undo(doc_change=True)
                w.field_value = val
            elif ft == pymupdf.PDF_WIDGET_TYPE_SIGNATURE:
                self.set_status("Signature field: use the Sign tool to place your signature on it.")
                return
            else:
                return
            w.update()
            self.mark()
            self.render_thumbs()
            self.redraw()
        except Exception as e:
            messagebox.showerror(core.APP_NAME, f"Couldn't fill this field:\n{e}", parent=self)

    # ---------------------------------------------------------------- saving
    def build_output(self):
        """A new document = current pages + all added objects written in."""
        out = pymupdf.open("pdf", self.doc.tobytes())
        if self.password:
            out.authenticate(self.password)
        for pno, objs in enumerate(self.objs):
            if not objs:
                continue
            page = out[pno]
            mat = page.derotation_matrix
            whites = [o for o in objs if o["type"] == "white"]
            for o in whites:  # real removal first, so later additions on top survive
                r = pymupdf.Rect(o["rect"]) * mat
                page.add_redact_annot(r, fill=(1, 1, 1))
            if whites:
                page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)
            for o in objs:
                t = o["type"]
                if t == "hl":
                    r = pymupdf.Rect(o["rect"]) * mat
                    a = page.add_highlight_annot(r.quad)
                    a.set_colors(stroke=core.hex_to_rgb(o["color"]))
                    a.update()
                elif t == "ink":
                    pts = [list(pymupdf.Point(p) * mat) for p in o["points"]]
                    a = page.add_ink_annot([pts])
                    a.set_colors(stroke=core.hex_to_rgb(o["color"]))
                    a.set_border(width=o["width"])
                    a.update()
                elif t == "image":
                    r = pymupdf.Rect(o["rect"]) * mat
                    r.normalize()
                    page.insert_image(r, stream=o["png"], rotate=page.rotation, keep_proportion=False, overlay=True)
                elif t == "text":
                    size = o["size"]
                    for i, line in enumerate(o["text"].split("\n")):
                        base = pymupdf.Point(o["x"], o["y"] + size * 0.93 + i * size * 1.2) * mat
                        page.insert_text(base, line, fontsize=size, fontname="helv",
                                         color=core.hex_to_rgb(o["color"]), rotate=page.rotation)
        return out

    def save(self, ask=False):
        if not self.doc:
            return False
        self._commit_text()
        path = self.path
        if ask or not path or os.path.splitext(path)[1].lower() != ".pdf":
            init = os.path.splitext(os.path.basename(path or "document"))[0] + (" (edited)" if path else "") + ".pdf"
            path = filedialog.asksaveasfilename(parent=self, title="Save PDF as", defaultextension=".pdf",
                                                initialdir=os.path.dirname(path or "") or self.settings.get("last_dir"),
                                                initialfile=init, filetypes=[("PDF", "*.pdf")])
            if not path:
                return False
        try:
            out = self.build_output()
            tmp = path + ".part"
            opts = dict(garbage=3, deflate=True)
            if self.password:
                opts.update(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=self.password, owner_pw=self.password)
            out.save(tmp, **opts)
            out.close()
            os.replace(tmp, path)
        except Exception as e:
            messagebox.showerror(core.APP_NAME, f"Couldn't save the PDF:\n{e}", parent=self)
            return False
        self.path = path
        self.dirty = False
        core.add_recent(self.settings, path)
        self._title()
        self.set_status(f"Saved {os.path.basename(path)}  ({core.human(os.path.getsize(path))})")
        return True


class SignaturePad(tk.Toplevel):
    def __init__(self, master, on_done):
        super().__init__(master)
        self.title("Draw your signature")
        self.transient(master.winfo_toplevel())
        self.on_done = on_done
        k = getattr(master, "k", 1.0)
        self.W, self.H = int(520 * k), int(200 * k)
        ttk.Label(self, text="Sign with your mouse, pen or finger:", padding=(12, 10, 12, 4)).pack(anchor="w")
        self.cv = tk.Canvas(self, width=self.W, height=self.H, bg="white", highlightthickness=1,
                            highlightbackground="#c5c8d2", cursor="pencil")
        self.cv.pack(padx=12)
        self.cv.create_line(20, self.H - 40, self.W - 20, self.H - 40, fill="#dde")
        self.strokes, self.cur = [], None
        self.cv.bind("<ButtonPress-1>", self._down)
        self.cv.bind("<B1-Motion>", self._move)
        self.cv.bind("<ButtonRelease-1>", lambda e: setattr(self, "cur", None))
        self.remember = tk.BooleanVar(value=True)
        bar = ttk.Frame(self, padding=12)
        bar.pack(fill="x")
        ttk.Checkbutton(bar, text="Remember this signature", variable=self.remember).pack(side="left")
        ttk.Button(bar, text="Use signature", command=self._ok).pack(side="right")
        ttk.Button(bar, text="Clear", command=self._clear).pack(side="right", padx=6)
        self.grab_set()

    def _down(self, e):
        self.cur = [(e.x, e.y)]
        self.strokes.append(self.cur)

    def _move(self, e):
        if self.cur is None:
            return
        a = self.cur[-1]
        self.cur.append((e.x, e.y))
        self.cv.create_line(a[0], a[1], e.x, e.y, width=3, capstyle="round", smooth=True, tags="ink", fill="#10204a")

    def _clear(self):
        self.strokes = []
        self.cv.delete("ink")

    def _ok(self):
        pts = [p for s in self.strokes for p in s]
        if len(pts) < 3:
            self.destroy()
            return
        s = 3
        img = Image.new("RGBA", (self.W * s, self.H * s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for st in self.strokes:
            if len(st) > 1:
                d.line([(x * s, y * s) for x, y in st], fill=(16, 32, 74, 255), width=3 * s, joint="curve")
            for x, y in (st[0], st[-1]):
                d.ellipse([x * s - 4, y * s - 4, x * s + 4, y * s + 4], fill=(16, 32, 74, 255))
        bbox = img.getbbox()
        img = img.crop((max(0, bbox[0] - 10), max(0, bbox[1] - 10), bbox[2] + 10, bbox[3] + 10))
        img.thumbnail((900, 400), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        self.destroy()
        self.on_done(buf.getvalue(), self.remember.get())


class ChoiceDialog(simpledialog.Dialog):
    def __init__(self, master, title, choices, current):
        self.choices, self.current, self.result = choices, current, None
        super().__init__(master, title)

    def body(self, master):
        self.var = tk.StringVar(value=self.current or (self.choices[0] if self.choices else ""))
        cb = ttk.Combobox(master, values=self.choices, textvariable=self.var, state="readonly", width=40)
        cb.pack(padx=10, pady=10)
        return cb

    def apply(self):
        self.result = self.var.get()

    @classmethod
    def ask(cls, master, title, choices, current):
        return cls(master, title, choices, current).result

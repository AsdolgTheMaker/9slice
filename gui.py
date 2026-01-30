"""
Tkinter-based 9-Slice Texture Editor GUI.

Layout
------
+-------------------------------+------------------+
|  Source image with draggable  |  3×3 grid preview |
|  guide lines                  |                   |
+-------------------------------+------------------+
|  Margin inputs  |  Export buttons  | Status        |
+-------------------------------+------------------+
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Tuple

from PIL import Image, ImageTk

import slicer


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GUIDE_COLOR = "#ff3333"
GUIDE_WIDTH = 2
CANVAS_BG = "#2b2b2b"
PREVIEW_BG = "#1e1e1e"
PREVIEW_GAP = 4          # pixels between preview cells
MAX_UNDO = 50


class App(tk.Tk):
    """Main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("9-Slice Texture Editor")
        self.configure(bg="#333")
        self.minsize(960, 600)

        # State -----------------------------------------------------------
        self._img: Optional[Image.Image] = None
        self._tk_img: Optional[ImageTk.PhotoImage] = None
        self._margins = slicer.Margins(0, 0, 0, 0)
        self._zoom: float = 1.0
        self._pan_offset: Tuple[float, float] = (0.0, 0.0)
        self._drag_guide: Optional[str] = None  # "left"/"right"/"top"/"bottom"
        self._undo_stack: List[slicer.Margins] = []
        self._redo_stack: List[slicer.Margins] = []
        self._pan_start: Optional[Tuple[int, int]] = None

        self._build_ui()
        self._bind_keys()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # Top area: source canvas (left) + preview (right)
        top = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        top.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Source canvas
        self._canvas = tk.Canvas(top, bg=CANVAS_BG, highlightthickness=0)
        top.add(self._canvas, weight=3)

        # Right side: preview + resolution label
        right_frame = ttk.Frame(top)
        top.add(right_frame, weight=2)

        top_bar = ttk.Frame(right_frame)
        top_bar.pack(side=tk.TOP, fill=tk.X, pady=(4, 2))

        self._res_var = tk.StringVar(value="")
        ttk.Label(top_bar, textvariable=self._res_var,
                  font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=4)

        self._show_guides = tk.BooleanVar(value=True)
        ttk.Checkbutton(top_bar, text="Show guides",
                        variable=self._show_guides,
                        command=self._redraw_preview).pack(side=tk.RIGHT, padx=4)

        self._preview = tk.Canvas(right_frame, bg=PREVIEW_BG, highlightthickness=0)
        self._preview.pack(fill=tk.BOTH, expand=True)

        # Bottom bar
        bot = ttk.Frame(self)
        bot.pack(fill=tk.X, padx=4, pady=(0, 4))

        # Load button
        ttk.Button(bot, text="Load Image…", command=self._load_image).pack(side=tk.LEFT, padx=2)

        ttk.Separator(bot, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        # Margin entries
        self._margin_vars: dict[str, tk.StringVar] = {}
        for label in ("Left", "Top", "Right", "Bottom"):
            ttk.Label(bot, text=f"{label}:").pack(side=tk.LEFT, padx=(4, 0))
            var = tk.StringVar(value="0")
            var.trace_add("write", self._on_entry_change)
            self._margin_vars[label.lower()] = var
            e = ttk.Entry(bot, textvariable=var, width=5, justify=tk.CENTER)
            e.pack(side=tk.LEFT, padx=2)

        ttk.Separator(bot, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        # Export buttons
        ttk.Button(bot, text="Export Corners", command=self._export_corners).pack(side=tk.LEFT, padx=2)
        ttk.Button(bot, text="Export JSON", command=self._export_json).pack(side=tk.LEFT, padx=2)
        ttk.Button(bot, text="Export 9 PNGs", command=self._export_pngs).pack(side=tk.LEFT, padx=2)
        ttk.Button(bot, text="Export Atlas", command=self._export_atlas).pack(side=tk.LEFT, padx=2)

        # Status label
        self._status_var = tk.StringVar(value="Load an image to begin.")
        ttk.Label(bot, textvariable=self._status_var).pack(side=tk.RIGHT, padx=4)

        # Canvas events
        self._canvas.bind("<Configure>", lambda _: self._redraw())
        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<MouseWheel>", self._on_scroll)
        self._canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self._canvas.bind("<B2-Motion>", self._on_pan_move)
        self._canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self._canvas.bind("<B3-Motion>", self._on_pan_move)

        self._preview.bind("<Configure>", lambda _: self._redraw_preview())
        self._preview.bind("<ButtonPress-1>", self._on_preview_click)

    def _bind_keys(self) -> None:
        self.bind("<Control-z>", lambda _: self._undo())
        self.bind("<Control-y>", lambda _: self._redo())
        self.bind("<Control-o>", lambda _: self._load_image())

    # ------------------------------------------------------------------
    # Image loading
    # ------------------------------------------------------------------
    def _load_image(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.tga"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            self._img = Image.open(path).convert("RGBA")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load image:\n{e}")
            return

        # Reset state — default margins at 25%
        self._margins = slicer.Margins(
            round(self._img.width * 0.25), round(self._img.width * 0.25),
            round(self._img.height * 0.25), round(self._img.height * 0.25),
        )
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._zoom = 1.0
        self._pan_offset = (0.0, 0.0)
        self._sync_entries()
        self._fit_zoom()
        self._redraw()
        self._redraw_preview()
        self._status_var.set(
            f"{os.path.basename(path)}  —  {self._img.width}×{self._img.height}"
        )

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------
    def _fit_zoom(self) -> None:
        """Set zoom so the image fits the canvas with some padding."""
        if self._img is None:
            return
        cw = self._canvas.winfo_width() or 600
        ch = self._canvas.winfo_height() or 400
        pad = 40
        zx = (cw - pad) / self._img.width
        zy = (ch - pad) / self._img.height
        self._zoom = min(zx, zy, 4.0)
        # Centre the image
        self._pan_offset = (
            (cw - self._img.width * self._zoom) / 2,
            (ch - self._img.height * self._zoom) / 2,
        )

    def _img_to_canvas(self, ix: float, iy: float) -> Tuple[float, float]:
        ox, oy = self._pan_offset
        return ix * self._zoom + ox, iy * self._zoom + oy

    def _canvas_to_img(self, cx: float, cy: float) -> Tuple[float, float]:
        ox, oy = self._pan_offset
        return (cx - ox) / self._zoom, (cy - oy) / self._zoom

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------
    def _redraw(self) -> None:
        c = self._canvas
        c.delete("all")
        if self._img is None:
            return

        z = self._zoom
        # Render image at current zoom
        display = self._img.resize(
            (max(1, int(self._img.width * z)), max(1, int(self._img.height * z))),
            Image.NEAREST if z >= 2 else Image.LANCZOS,
        )
        self._tk_img = ImageTk.PhotoImage(display)
        ox, oy = self._pan_offset
        c.create_image(ox, oy, anchor=tk.NW, image=self._tk_img)

        # Guide lines
        m = self._margins
        w, h = self._img.width, self._img.height
        # Vertical guides (left, right)
        for ix in (m.left, w - m.right):
            x0, y0 = self._img_to_canvas(ix, 0)
            x1, y1 = self._img_to_canvas(ix, h)
            c.create_line(x0, y0, x1, y1, fill=GUIDE_COLOR, width=GUIDE_WIDTH, tags="guide")
        # Horizontal guides (top, bottom)
        for iy in (m.top, h - m.bottom):
            x0, y0 = self._img_to_canvas(0, iy)
            x1, y1 = self._img_to_canvas(w, iy)
            c.create_line(x0, y0, x1, y1, fill=GUIDE_COLOR, width=GUIDE_WIDTH, tags="guide")

    def _redraw_preview(self) -> None:
        pv = self._preview
        pv.delete("all")
        self._pv_img = None  # prevent GC
        if self._img is None:
            self._res_var.set("")
            return

        stitched = slicer.stitch_corners(self._img, self._margins)
        sw, sh = stitched.size
        self._res_var.set(f"Result: {sw} x {sh} px")

        if sw == 0 or sh == 0:
            return

        pw = pv.winfo_width() or 300
        ph = pv.winfo_height() or 300
        pad = 16
        scale = min((pw - pad) / sw, (ph - pad) / sh, 4.0)
        if scale <= 0:
            scale = 1

        display_w = max(1, int(sw * scale))
        display_h = max(1, int(sh * scale))
        resized = stitched.resize((display_w, display_h),
                                  Image.NEAREST if scale >= 2 else Image.LANCZOS)
        self._pv_img = ImageTk.PhotoImage(resized)
        x = pw // 2
        y = ph // 2
        pv.create_image(x, y, anchor=tk.CENTER, image=self._pv_img)
        # Draw a divider cross and margin percentages
        if self._show_guides.get():
            m = self._margins
            iw, ih = self._img.width, self._img.height
            cx = int(m.left * scale)
            cy = int(m.top * scale)
            ox = x - display_w // 2
            oy = y - display_h // 2
            pv.create_line(ox + cx, oy, ox + cx, oy + display_h,
                           fill="#ffffff", width=1, dash=(4, 4))
            pv.create_line(ox, oy + cy, ox + display_w, oy + cy,
                           fill="#ffffff", width=1, dash=(4, 4))

            # Margin ratios (fraction of source image dimension)
            rl = m.left / iw if iw else 0
            rr = m.right / iw if iw else 0
            rt = m.top / ih if ih else 0
            rb = m.bottom / ih if ih else 0
            label_cfg = dict(fill="#cccccc", font=("TkDefaultFont", 9))
            pad_px = 4

            # Left — outside left edge, vertically centred
            pv.create_text(ox - pad_px, oy + display_h // 2,
                           anchor=tk.E, text=f"{rl:.2f}", **label_cfg)
            # Right — outside right edge, vertically centred
            pv.create_text(ox + display_w + pad_px, oy + display_h // 2,
                           anchor=tk.W, text=f"{rr:.2f}", **label_cfg)
            # Top — outside top edge, horizontally centred
            pv.create_text(ox + display_w // 2, oy - pad_px,
                           anchor=tk.S, text=f"{rt:.2f}", **label_cfg)
            # Bottom — outside bottom edge, horizontally centred
            pv.create_text(ox + display_w // 2, oy + display_h + pad_px,
                           anchor=tk.N, text=f"{rb:.2f}", **label_cfg)

    # ------------------------------------------------------------------
    # Guide interaction
    # ------------------------------------------------------------------
    _GRAB_TOLERANCE = 8  # pixels on canvas

    def _hit_guide(self, cx: float, cy: float) -> Optional[str]:
        """Return which guide is near (cx, cy) on the canvas, or None."""
        if self._img is None:
            return None
        m = self._margins
        w, h = self._img.width, self._img.height
        tol = self._GRAB_TOLERANCE

        checks = [
            ("left",   self._img_to_canvas(m.left, 0)[0]),
            ("right",  self._img_to_canvas(w - m.right, 0)[0]),
        ]
        for name, gx in checks:
            if abs(cx - gx) < tol:
                return name

        checks_h = [
            ("top",    self._img_to_canvas(0, m.top)[1]),
            ("bottom", self._img_to_canvas(0, h - m.bottom)[1]),
        ]
        for name, gy in checks_h:
            if abs(cy - gy) < tol:
                return name
        return None

    def _on_preview_click(self, event: tk.Event) -> None:
        if self._img is None:
            self._load_image()

    def _on_press(self, event: tk.Event) -> None:
        if self._img is None:
            self._load_image()
            return
        guide = self._hit_guide(event.x, event.y)
        if guide:
            self._push_undo()
            self._drag_guide = guide
            self._canvas.config(cursor="sb_h_double_arrow" if guide in ("left", "right")
                                else "sb_v_double_arrow")

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_guide is None or self._img is None:
            return
        ix, iy = self._canvas_to_img(event.x, event.y)
        w, h = self._img.width, self._img.height
        g = self._drag_guide
        if g == "left":
            self._margins.left = max(0, min(int(ix), w - self._margins.right))
        elif g == "right":
            self._margins.right = max(0, min(int(w - ix), w - self._margins.left))
        elif g == "top":
            self._margins.top = max(0, min(int(iy), h - self._margins.bottom))
        elif g == "bottom":
            self._margins.bottom = max(0, min(int(h - iy), h - self._margins.top))
        self._sync_entries()
        self._redraw()
        self._redraw_preview()

    def _on_release(self, event: tk.Event) -> None:
        self._drag_guide = None
        self._canvas.config(cursor="")

    # ------------------------------------------------------------------
    # Zoom / Pan
    # ------------------------------------------------------------------
    def _on_scroll(self, event: tk.Event) -> None:
        if self._img is None:
            return
        # Zoom towards cursor
        old_z = self._zoom
        factor = 1.1 if event.delta > 0 else 1 / 1.1
        self._zoom = max(0.1, min(self._zoom * factor, 16.0))

        # Adjust pan so the point under the cursor stays fixed
        cx, cy = event.x, event.y
        ox, oy = self._pan_offset
        ratio = self._zoom / old_z
        self._pan_offset = (
            cx - (cx - ox) * ratio,
            cy - (cy - oy) * ratio,
        )
        self._redraw()

    def _on_pan_start(self, event: tk.Event) -> None:
        self._pan_start = (event.x, event.y)

    def _on_pan_move(self, event: tk.Event) -> None:
        if self._pan_start is None:
            return
        dx = event.x - self._pan_start[0]
        dy = event.y - self._pan_start[1]
        ox, oy = self._pan_offset
        self._pan_offset = (ox + dx, oy + dy)
        self._pan_start = (event.x, event.y)
        self._redraw()

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------
    def _push_undo(self) -> None:
        m = self._margins
        self._undo_stack.append(slicer.Margins(m.left, m.right, m.top, m.bottom))
        if len(self._undo_stack) > MAX_UNDO:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        m = self._margins
        self._redo_stack.append(slicer.Margins(m.left, m.right, m.top, m.bottom))
        self._margins = self._undo_stack.pop()
        self._sync_entries()
        self._redraw()
        self._redraw_preview()

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        m = self._margins
        self._undo_stack.append(slicer.Margins(m.left, m.right, m.top, m.bottom))
        self._margins = self._redo_stack.pop()
        self._sync_entries()
        self._redraw()
        self._redraw_preview()

    # ------------------------------------------------------------------
    # Entry ↔ margins sync
    # ------------------------------------------------------------------
    _syncing = False

    def _sync_entries(self) -> None:
        """Push current margins into the entry StringVars."""
        self._syncing = True
        self._margin_vars["left"].set(str(self._margins.left))
        self._margin_vars["right"].set(str(self._margins.right))
        self._margin_vars["top"].set(str(self._margins.top))
        self._margin_vars["bottom"].set(str(self._margins.bottom))
        self._syncing = False

    def _on_entry_change(self, *_args) -> None:
        """User typed a value — update margins."""
        if self._syncing or self._img is None:
            return
        try:
            l = int(self._margin_vars["left"].get() or 0)
            r = int(self._margin_vars["right"].get() or 0)
            t = int(self._margin_vars["top"].get() or 0)
            b = int(self._margin_vars["bottom"].get() or 0)
        except ValueError:
            return
        w, h = self._img.width, self._img.height
        l = max(0, min(l, w - r if r < w else w))
        r = max(0, min(r, w - l if l < w else w))
        t = max(0, min(t, h - b if b < h else h))
        b = max(0, min(b, h - t if t < h else h))
        new = slicer.Margins(l, r, t, b)
        if new != self._margins:
            self._push_undo()
            self._margins = new
            self._redraw()
            self._redraw_preview()

    # ------------------------------------------------------------------
    # Export actions
    # ------------------------------------------------------------------
    def _ensure_image(self) -> bool:
        if self._img is None:
            messagebox.showwarning("No image", "Load an image first.")
            return False
        return True

    def _export_corners(self) -> None:
        if not self._ensure_image():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG", "*.png")]
        )
        if not path:
            return
        slicer.export_corners(self._img, self._margins, path)
        result = slicer.stitch_corners(self._img, self._margins)
        self._status_var.set(
            f"Saved corners ({result.width}x{result.height}) → {os.path.basename(path)}"
        )

    def _export_json(self) -> None:
        if not self._ensure_image():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")]
        )
        if not path:
            return
        slicer.export_json(self._img.width, self._img.height, self._margins, path)
        self._status_var.set(f"Saved JSON → {os.path.basename(path)}")

    def _export_pngs(self) -> None:
        if not self._ensure_image():
            return
        directory = filedialog.askdirectory(title="Choose output folder")
        if not directory:
            return
        paths = slicer.export_slices(self._img, self._margins, directory)
        self._status_var.set(f"Saved {len(paths)} PNGs → {directory}")

    def _export_atlas(self) -> None:
        if not self._ensure_image():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG", "*.png")]
        )
        if not path:
            return
        slicer.export_atlas(self._img, self._margins, path)
        self._status_var.set(f"Saved atlas → {os.path.basename(path)}")

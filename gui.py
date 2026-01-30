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
        self.state("zoomed")

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
        # Top toolbar
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=4, pady=(4, 0))

        # Load button
        ttk.Button(toolbar, text="Load Image…", command=self._load_image).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        # Margin entries
        self._margin_vars: dict[str, tk.StringVar] = {}
        for label in ("Left", "Top", "Right", "Bottom"):
            ttk.Label(toolbar, text=f"{label}:").pack(side=tk.LEFT, padx=(4, 0))
            var = tk.StringVar(value="0")
            var.trace_add("write", self._on_entry_change)
            self._margin_vars[label.lower()] = var
            e = ttk.Entry(toolbar, textvariable=var, width=5, justify=tk.CENTER)
            e.pack(side=tk.LEFT, padx=2)

        # Main area: source canvas (left) + preview (right)
        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Source canvas
        self._canvas = tk.Canvas(main, bg=CANVAS_BG, highlightthickness=0)
        main.add(self._canvas, weight=3)

        # Right side: preview controls + preview canvas
        right_frame = ttk.Frame(main)
        main.add(right_frame, weight=2)

        preview_bar = ttk.Frame(right_frame)
        preview_bar.pack(side=tk.TOP, fill=tk.X, pady=(4, 2))

        self._preview_mode = tk.StringVar(value="Stitched Corners")
        for mode in ("Stitched Corners", "9-Slice", "JSON"):
            ttk.Radiobutton(preview_bar, text=mode, variable=self._preview_mode,
                            value=mode, command=self._on_mode_change).pack(side=tk.LEFT, padx=4)

        self._show_guides = tk.BooleanVar(value=True)
        ttk.Checkbutton(preview_bar, text="Guides",
                        variable=self._show_guides,
                        command=self._redraw_preview).pack(side=tk.RIGHT, padx=4)

        self._res_var = tk.StringVar(value="")
        ttk.Label(preview_bar, textvariable=self._res_var,
                  font=("TkDefaultFont", 10, "bold")).pack(side=tk.RIGHT, padx=8)

        # Export button row
        export_bar = ttk.Frame(right_frame)
        export_bar.pack(side=tk.TOP, fill=tk.X, pady=(2, 4))

        self._export_btn = ttk.Button(export_bar, text="Export Stitched Corners", command=self._export_current)
        self._export_btn.pack(side=tk.LEFT, padx=2)

        # Preview canvas (for image modes)
        self._preview = tk.Canvas(right_frame, bg=PREVIEW_BG, highlightthickness=0)

        # JSON text widget (for JSON mode) with scrollbar
        self._json_frame = ttk.Frame(right_frame)
        self._json_text = tk.Text(self._json_frame, bg=PREVIEW_BG, fg="#cccccc",
                                  font=("Consolas", 11), wrap=tk.NONE,
                                  insertbackground="#cccccc", borderwidth=0,
                                  highlightthickness=0, padx=12, pady=8,
                                  state=tk.DISABLED)
        json_scroll_y = ttk.Scrollbar(self._json_frame, orient=tk.VERTICAL,
                                      command=self._json_text.yview)
        json_scroll_x = ttk.Scrollbar(self._json_frame, orient=tk.HORIZONTAL,
                                      command=self._json_text.xview)
        self._json_text.configure(yscrollcommand=json_scroll_y.set,
                                  xscrollcommand=json_scroll_x.set)
        json_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        json_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self._json_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # JSON syntax color tags
        self._json_text.tag_configure("key", foreground="#9cdcfe")
        self._json_text.tag_configure("string", foreground="#ce9178")
        self._json_text.tag_configure("number", foreground="#b5cea8")
        self._json_text.tag_configure("brace", foreground="#d4d4d4")
        self._json_text.tag_configure("colon", foreground="#d4d4d4")
        self._json_text.tag_configure("comma", foreground="#d4d4d4")

        # Show canvas by default
        self._preview.pack(fill=tk.BOTH, expand=True)

        # Status bar at bottom
        status_bar = ttk.Frame(self)
        status_bar.pack(fill=tk.X, padx=4, pady=(0, 4))

        self._status_var = tk.StringVar(value="Load an image to begin.")
        ttk.Label(status_bar, textvariable=self._status_var).pack(side=tk.LEFT, padx=4)

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
        self._canvas.bind("<Motion>", self._on_hover)

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

        # Guide lines + grip handles
        m = self._margins
        w, h = self._img.width, self._img.height
        box_size = 24     # square box side length
        grip_pad = 5      # padding inside box before grip lines
        grip_gap = 6      # vertical spacing between the 3 lines
        box_color = "#444444"
        line_color = "#999999"

        def _draw_grip(cx: float, cy: float) -> None:
            """Draw a square grip handle centred at (cx, cy) with 3 horizontal lines."""
            half = box_size / 2
            c.create_rectangle(cx - half, cy - half, cx + half, cy + half,
                               fill=box_color, outline=box_color, tags="guide")
            stroke_half = half - grip_pad
            for offset in (-grip_gap, 0, grip_gap):
                ly = cy + offset
                c.create_line(cx - stroke_half, ly, cx + stroke_half, ly,
                              fill=line_color, width=1, tags="guide")

        # Vertical guides (left, right)
        for ix in (m.left, w - m.right):
            x0, y0 = self._img_to_canvas(ix, 0)
            x1, y1 = self._img_to_canvas(ix, h)
            c.create_line(x0, y0, x1, y1, fill=GUIDE_COLOR, width=GUIDE_WIDTH, tags="guide")
            _draw_grip(x0, y0 - box_size / 2 - 1)
            _draw_grip(x0, y1 + box_size / 2 + 1)

        # Horizontal guides (top, bottom)
        for iy in (m.top, h - m.bottom):
            x0, y0 = self._img_to_canvas(0, iy)
            x1, y1 = self._img_to_canvas(w, iy)
            c.create_line(x0, y0, x1, y1, fill=GUIDE_COLOR, width=GUIDE_WIDTH, tags="guide")
            _draw_grip(x0 - box_size / 2 - 1, y0)
            _draw_grip(x1 + box_size / 2 + 1, y0)

    def _redraw_preview(self) -> None:
        pv = self._preview
        pv.delete("all")
        self._pv_img = None
        self._pv_imgs: list[ImageTk.PhotoImage] = []
        if self._img is None:
            self._res_var.set("")
            return

        mode = self._preview_mode.get()
        if mode == "Stitched Corners":
            self._preview_corners()
        elif mode == "9-Slice":
            self._preview_9slice()
        elif mode == "JSON":
            self._preview_json()

    # -- helper: fit an image onto the preview canvas and return placement info
    def _fit_to_preview(self, img: Image.Image) -> Optional[Tuple[ImageTk.PhotoImage, int, int, int, int, float]]:
        """Scale *img* to fit the preview canvas. Returns (tk_img, cx, cy, dw, dh, scale) or None."""
        sw, sh = img.size
        if sw == 0 or sh == 0:
            return None
        pv = self._preview
        pw = pv.winfo_width() or 300
        ph = pv.winfo_height() or 300
        pad = 16
        scale = min((pw - pad) / sw, (ph - pad) / sh, 4.0)
        if scale <= 0:
            scale = 1
        dw = max(1, int(sw * scale))
        dh = max(1, int(sh * scale))
        resized = img.resize((dw, dh), Image.NEAREST if scale >= 2 else Image.LANCZOS)
        tki = ImageTk.PhotoImage(resized)
        cx = pw // 2
        cy = ph // 2
        return tki, cx, cy, dw, dh, scale

    def _draw_margin_labels(self, ox: float, oy: float, dw: int, dh: int) -> None:
        """Draw margin ratio labels outside the preview image edges."""
        pv = self._preview
        m = self._margins
        iw, ih = self._img.width, self._img.height
        rl = m.left / iw if iw else 0
        rr = m.right / iw if iw else 0
        rt = m.top / ih if ih else 0
        rb = m.bottom / ih if ih else 0
        label_cfg = dict(fill="#cccccc", font=("TkDefaultFont", 9))
        pad_px = 4
        pv.create_text(ox - pad_px, oy + dh // 2,
                       anchor=tk.E, text=f"{rl:.2f}", **label_cfg)
        pv.create_text(ox + dw + pad_px, oy + dh // 2,
                       anchor=tk.W, text=f"{rr:.2f}", **label_cfg)
        pv.create_text(ox + dw // 2, oy - pad_px,
                       anchor=tk.S, text=f"{rt:.2f}", **label_cfg)
        pv.create_text(ox + dw // 2, oy + dh + pad_px,
                       anchor=tk.N, text=f"{rb:.2f}", **label_cfg)

    def _preview_corners(self) -> None:
        pv = self._preview
        stitched = slicer.stitch_corners(self._img, self._margins)
        sw, sh = stitched.size
        self._res_var.set(f"Result: {sw} x {sh} px")
        result = self._fit_to_preview(stitched)
        if result is None:
            return
        tki, cx, cy, dw, dh, scale = result
        self._pv_img = tki
        pv.create_image(cx, cy, anchor=tk.CENTER, image=tki)
        if self._show_guides.get():
            m = self._margins
            gx = int(m.left * scale)
            gy = int(m.top * scale)
            ox = cx - dw // 2
            oy = cy - dh // 2
            pv.create_line(ox + gx, oy, ox + gx, oy + dh,
                           fill="#ffffff", width=1, dash=(4, 4))
            pv.create_line(ox, oy + gy, ox + dw, oy + gy,
                           fill="#ffffff", width=1, dash=(4, 4))
            self._draw_margin_labels(ox, oy, dw, dh)

    def _preview_9slice(self) -> None:
        pv = self._preview
        slices = slicer.slice_image(self._img, self._margins)
        pw = pv.winfo_width() or 300
        ph = pv.winfo_height() or 300

        col_widths = [slices["corner_tl"].width, slices["edge_top"].width, slices["corner_tr"].width]
        row_heights = [slices["corner_tl"].height, slices["edge_left"].height, slices["corner_bl"].height]
        self._res_var.set(f"Source: {self._img.width} x {self._img.height} px")

        gap = PREVIEW_GAP
        total_w = sum(col_widths) or 1
        total_h = sum(row_heights) or 1
        avail_w = pw - gap * 4
        avail_h = ph - gap * 4
        scale = min(avail_w / total_w, avail_h / total_h, 4.0)
        if scale <= 0:
            scale = 1

        grid_w = sum(max(1, int(cw * scale)) for cw in col_widths) + gap * 2
        grid_h = sum(max(1, int(rh * scale)) for rh in row_heights) + gap * 2
        start_x = (pw - grid_w) // 2
        start_y = (ph - grid_h) // 2

        y = start_y
        idx = 0
        for row in range(3):
            x = start_x
            rh = max(1, int(row_heights[row] * scale))
            for col in range(3):
                name = slicer.SLICE_NAMES[idx]
                cw_px = max(1, int(col_widths[col] * scale))
                sub = slices[name]
                if sub.width > 0 and sub.height > 0:
                    resized = sub.resize((cw_px, rh), Image.LANCZOS)
                    tki = ImageTk.PhotoImage(resized)
                    self._pv_imgs.append(tki)
                    pv.create_image(x, y, anchor=tk.NW, image=tki)
                    pv.create_rectangle(x, y, x + cw_px, y + rh, outline="#555", width=1)
                x += cw_px + gap
                idx += 1
            y += rh + gap

    def _preview_json(self) -> None:
        import json as json_mod
        import re

        m = self._margins
        iw, ih = self._img.width, self._img.height
        regions = slicer.compute_regions(iw, ih, m)
        self._res_var.set("")

        data = {
            "image_size": {"width": iw, "height": ih},
            "margins": {"left": m.left, "right": m.right, "top": m.top, "bottom": m.bottom},
            "slices": {name: {"x": b[0], "y": b[1], "w": b[2] - b[0], "h": b[3] - b[1]}
                       for name, b in regions.items()},
        }
        text = json_mod.dumps(data, indent=2)

        tw = self._json_text
        tw.config(state=tk.NORMAL)
        tw.delete("1.0", tk.END)
        tw.insert("1.0", text)

        # Apply syntax highlighting
        for tag in ("key", "string", "number", "brace", "colon", "comma"):
            tw.tag_remove(tag, "1.0", tk.END)

        for match in re.finditer(r'"[^"]*"\s*:', text):
            # key (including the colon)
            start = f"1.0+{match.start()}c"
            colon_pos = match.end() - 1
            end_key = f"1.0+{colon_pos}c"
            end_colon = f"1.0+{match.end()}c"
            tw.tag_add("key", start, end_key)
            tw.tag_add("colon", end_key, end_colon)

        for match in re.finditer(r':\s*"([^"]*)"', text):
            # string values (just the quoted part)
            val_start = text.index('"', match.start() + 1)
            val_end = match.end()
            tw.tag_add("string", f"1.0+{val_start}c", f"1.0+{val_end}c")

        for match in re.finditer(r'(?<=[\s:,\[])(-?\d+\.?\d*)', text):
            tw.tag_add("number", f"1.0+{match.start()}c", f"1.0+{match.end()}c")

        for match in re.finditer(r'[{}\[\]]', text):
            tw.tag_add("brace", f"1.0+{match.start()}c", f"1.0+{match.end()}c")

        for match in re.finditer(r',', text):
            tw.tag_add("comma", f"1.0+{match.start()}c", f"1.0+{match.end()}c")

        tw.config(state=tk.DISABLED)

    _EXPORT_LABELS = {
        "Stitched Corners": "Export Stitched Corners",
        "9-Slice": "Export 9 PNGs",
        "JSON": "Export JSON",
    }

    def _on_mode_change(self) -> None:
        mode = self._preview_mode.get()
        self._export_btn.config(text=self._EXPORT_LABELS.get(mode, "Export"))
        # Swap between canvas and JSON text widget
        if mode == "JSON":
            self._preview.pack_forget()
            self._json_frame.pack(fill=tk.BOTH, expand=True)
        else:
            self._json_frame.pack_forget()
            self._preview.pack(fill=tk.BOTH, expand=True)
        self._redraw_preview()

    def _export_current(self) -> None:
        mode = self._preview_mode.get()
        if mode == "Stitched Corners":
            self._export_corners()
        elif mode == "9-Slice":
            self._export_pngs()
        elif mode == "JSON":
            self._export_json()

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

    def _on_hover(self, event: tk.Event) -> None:
        if self._drag_guide is not None:
            return  # already dragging, cursor set by _on_press
        guide = self._hit_guide(event.x, event.y)
        self._canvas.config(cursor="fleur" if guide else "")

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



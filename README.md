# 9-Slice Texture Editor

Desktop tool for defining 9-slice boundaries on an image. Load a texture, drag the four margin guides, see a live preview of the stitched corners, and export the result.

## What it does

You have a texture with decorative corners and stretchable edges (a UI panel, a button skin, a dialog frame). This tool lets you visually set the four slice margins and then export:

- **Stitched corners image** — the four corners joined into a single PNG, with live preview and output resolution displayed as you edit
- **9 individual PNGs** — each slice as a separate file
- **JSON coordinates** — margin values and per-slice regions for game engines

## Requirements

- Python 3.10+
- Pillow (`pip install Pillow`)

## Usage

```
python main.py
```

Or double-click `9slice.bat` on Windows.

## Controls

- **Left-click drag** on a guide line to move it
- **Mouse wheel** to zoom
- **Right-click drag** to pan
- **Ctrl+Z / Ctrl+Y** for undo/redo
- Margin values are also editable as numbers in the toolbar
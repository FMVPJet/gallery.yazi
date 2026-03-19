#!/usr/bin/env python3

import base64
import hashlib
import os
import re
import select
import shutil
import subprocess
import sys
import termios
import threading
import tty
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".heic",
    ".avif",
}

TOP_MARGIN = 1
FOOTER_LINES = 4
GAP_X = 2
GAP_Y = 1
THUMB_MAX_EDGE = 640
LABEL_LINES = 1
FULL_MAX_EDGE = 2048

ESC = "\x1b"
CSI = f"{ESC}["
OSC_KITTY = f"{ESC}_G"
ST = f"{ESC}\\"
RESET = f"{CSI}0m"
SELECTED_STYLE = f"{CSI}1;97m"
BORDER_STYLE = f"{CSI}1;96m"
ACCENT_STYLE = f"{CSI}1;96m"
MUTED_STYLE = f"{CSI}2;37m"
MARKED_STYLE = f"{CSI}1;92m"
UNMARKED_STYLE = f"{CSI}0;37m"

PRELOAD_ROWS = 2
MIN_THUMB_COLS = 14
MAX_THUMB_COLS = 30
PREFERRED_CELL_WIDTH = 22
MAX_GRID_COLUMNS = 8
CELL_PIXEL_WIDTH = 24
CELL_PIXEL_HEIGHT = 48
MAGICK_PATH = shutil.which("magick")


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def natural_key(value: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def truncate_middle(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]

    head = max(1, (limit - 1) // 2)
    tail = max(1, limit - head - 1)
    return f"{value[:head]}…{value[-tail:]}"


def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    unit_index = 0

    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    if unit_index == 0:
        return f"{int(value)} {units[unit_index]}"
    return f"{value:.1f} {units[unit_index]}"


def format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def pad_visible(text: str, width: int) -> str:
    visible = max(0, width - len(re.sub(r"\x1b\[[0-9;]*m", "", text)))
    return text + (" " * visible)


def is_image(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def resolve_target(raw_path: str):
    if not raw_path:
        return None, None

    candidate = Path(raw_path).expanduser()
    if candidate.is_dir():
        return candidate, None

    if candidate.is_file():
        return candidate.parent, candidate if is_image(candidate) else None

    return None, None


def collect_selected_images(raw_paths, target_dir: Optional[Path] = None):
    images = []
    seen = set()

    for raw_path in raw_paths:
        if not raw_path:
            continue
        candidate = Path(raw_path).expanduser()
        if not candidate.is_file() or not is_image(candidate):
            continue
        if target_dir is not None and candidate.parent != target_dir:
            continue

        identity = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if identity in seen:
            continue

        seen.add(identity)
        images.append(candidate)

    images.sort(key=lambda item: (str(item.parent).lower(), natural_key(item.name)))
    return images


def collect_images(directory: Path):
    items = [item for item in directory.iterdir() if item.is_file() and is_image(item)]
    items.sort(key=lambda item: natural_key(item.name))
    return items


def resolve_gallery_inputs(args):
    hovered = args[1] if len(args) > 1 else ""
    selected_file = Path(args[2]).expanduser() if len(args) > 2 and args[2] else None

    selected = []
    if selected_file and selected_file.is_file():
        try:
            selected = [
                line.strip()
                for line in selected_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except OSError:
            selected = []

    target_dir, start_image = resolve_target(hovered)
    selected_images = collect_selected_images(selected, target_dir)
    if selected_images:
        hovered_path = Path(hovered).expanduser() if hovered else None
        start_image = hovered_path if hovered_path in selected_images else selected_images[0]
        initial_selected = {str(path) for path in selected_images}
        source_label = target_dir.name or str(target_dir) if target_dir is not None else "Selection"
        return "Selection", source_label, selected_images, start_image, initial_selected

    if target_dir is None:
        return None, None, [], None, set()

    return "Directory", target_dir.name or str(target_dir), collect_images(target_dir), start_image, set()


def thumbnail_cache_root() -> Path:
    base = Path(os.environ.get("TMPDIR") or "/tmp")
    return base / "gallery-yazi-thumbs"


def thumbnail_path(image_path: Path, canvas_width: int, canvas_height: int) -> Path:
    stat = image_path.stat()
    digest = hashlib.sha1(
        f"{image_path}\0{stat.st_mtime_ns}\0{stat.st_size}\0{canvas_width}x{canvas_height}".encode("utf-8")
    ).hexdigest()
    return thumbnail_cache_root() / f"{digest}.png"


@lru_cache(maxsize=1024)
def image_dimensions(image_path: str):
    if MAGICK_PATH:
        result = subprocess.run(
            [MAGICK_PATH, "identify", "-ping", "-format", "%w %h", image_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                return int(parts[0]), int(parts[1])

    result = subprocess.run(
        ["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", "-1", image_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        match = re.search(r"pixelWidth:\s*(\d+)\|pixelHeight:\s*(\d+)", result.stdout)
        if match:
            return int(match.group(1)), int(match.group(2))

    return None, None


def fit_image_cells(image_path: Path, max_cols: int, max_rows: int):
    img_width, img_height = image_dimensions(str(image_path))
    if not img_width or not img_height:
        return max_cols, max_rows

    available_width = max_cols * CELL_PIXEL_WIDTH
    available_height = max_rows * CELL_PIXEL_HEIGHT
    scale = min(available_width / img_width, available_height / img_height)

    display_width = max(CELL_PIXEL_WIDTH, int(round(img_width * scale)))
    display_height = max(CELL_PIXEL_HEIGHT, int(round(img_height * scale)))

    display_cols = clamp(int(round(display_width / CELL_PIXEL_WIDTH)), 1, max_cols)
    display_rows = clamp(int(round(display_height / CELL_PIXEL_HEIGHT)), 1, max_rows)
    return display_cols, display_rows


def ensure_thumbnail(image_path: Path, canvas_width: int, canvas_height: int):
    thumb_path = thumbnail_path(image_path, canvas_width, canvas_height)
    if thumb_path.exists():
        return thumb_path

    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    if MAGICK_PATH:
        result = subprocess.run(
            [
                MAGICK_PATH,
                str(image_path),
                "-auto-orient",
                "-thumbnail",
                f"{canvas_width}x{canvas_height}",
                "-background",
                "none",
                "-gravity",
                "center",
                "-extent",
                f"{canvas_width}x{canvas_height}",
                f"png:{thumb_path}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0 and thumb_path.exists():
            return thumb_path

    result = subprocess.run(
        [
            "/usr/bin/sips",
            "-s",
            "format",
            "png",
            "-Z",
            str(min(max(canvas_width, canvas_height), THUMB_MAX_EDGE)),
            str(image_path),
            "--out",
            str(thumb_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode == 0 and thumb_path.exists():
        return thumb_path
    return None


def preload_thumbnails(image_paths, canvas_width: int, canvas_height: int):
    if not image_paths:
        return

    for image_path in image_paths:
        ensure_thumbnail(image_path, canvas_width, canvas_height)


def row_image_paths(images, row_start: int, row_count: int, grid_columns: int):
    if row_count <= 0:
        return []

    start = max(0, row_start * grid_columns)
    end = min(len(images), start + row_count * grid_columns)
    return images[start:end]


def build_visible_images(all_images, marked_paths, show_marked_only: bool):
    if not show_marked_only:
        return list(all_images)
    return [image_path for image_path in all_images if str(image_path) in marked_paths]


def resolve_selected_image(all_images, all_positions, visible_images, selected_path: Optional[Path]):
    if not visible_images:
        return None, 0

    if selected_path in visible_images:
        return selected_path, visible_images.index(selected_path)

    anchor = all_positions.get(str(selected_path), 0)
    best_forward = None
    best_backward = None

    for visible_path in visible_images:
        visible_index = all_positions.get(str(visible_path), 0)
        if visible_index >= anchor and best_forward is None:
            best_forward = visible_path
        if visible_index <= anchor:
            best_backward = visible_path

    chosen = best_forward or best_backward or visible_images[0]
    return chosen, visible_images.index(chosen)


def write(data: str):
    sys.stdout.write(data)


def flush():
    sys.stdout.flush()


def clear_images():
    write(f"{OSC_KITTY}a=d,d=A,q=2;{ST}")


def clear_screen():
    write(f"{CSI}2J{CSI}H")


def move_cursor(row: int, column: int):
    write(f"{CSI}{row};{column}H")


def hide_cursor():
    write(f"{CSI}?25l")


def show_cursor():
    write(f"{CSI}?25h")


def kitty_image(path: Path, row: int, column: int, cols: int, rows: int):
    payload = base64.b64encode(str(path).encode("utf-8")).decode("ascii")
    move_cursor(row, column)
    write(f"{OSC_KITTY}a=T,f=100,t=f,c={cols},r={rows},C=1,q=2;{payload}{ST}")


def clear_rect(row: int, column: int, width: int, height: int):
    blank = " " * max(0, width)
    for offset in range(max(0, height)):
        move_cursor(row + offset, column)
        write(blank)


def draw_selection_frame(row: int, column: int, width: int, image_height: int):
    top_row = row
    bottom_row = row + image_height - 1
    left_col = column
    right_col = column + max(0, width) - 1
    inner_width = max(0, width - 2)

    move_cursor(top_row, left_col)
    write(f"{BORDER_STYLE}╔{'═' * inner_width}╗{RESET}")
    move_cursor(bottom_row, left_col)
    write(f"{BORDER_STYLE}╚{'═' * inner_width}╝{RESET}")

    for current_row in range(top_row + 1, bottom_row):
        move_cursor(current_row, left_col)
        write(f"{BORDER_STYLE}║{RESET}")
        move_cursor(current_row, right_col)
        write(f"{BORDER_STYLE}║{RESET}")


def draw_mark_frame(row: int, column: int, width: int, image_height: int):
    top_row = row
    bottom_row = row + image_height - 1
    left_col = column
    right_col = column + max(0, width) - 1
    inner_width = max(0, width - 2)

    move_cursor(top_row, left_col)
    write(f"{MARKED_STYLE}┌{'─' * inner_width}┐{RESET}")
    move_cursor(bottom_row, left_col)
    write(f"{MARKED_STYLE}└{'─' * inner_width}┘{RESET}")

    for current_row in range(top_row + 1, bottom_row):
        move_cursor(current_row, left_col)
        write(f"{MARKED_STYLE}│{RESET}")
        move_cursor(current_row, right_col)
        write(f"{MARKED_STYLE}│{RESET}")


def marked_label(name: str, width: int, is_marked: bool) -> str:
    prefix = "[M] " if is_marked else "    "
    return truncate_middle(prefix + name, width)


def cell_position(index: int, grid_columns: int, thumb_cols: int, thumb_rows: int):
    row = TOP_MARGIN + 1 + (index // grid_columns) * (thumb_rows + LABEL_LINES + GAP_Y)
    column = 1 + (index % grid_columns) * (thumb_cols + GAP_X)
    return row, column


def clear_cell_overlay(row: int, column: int, thumb_cols: int, thumb_rows: int):
    clear_rect(row, column, thumb_cols, 1)
    if thumb_rows > 1:
        for inner_row in range(row + 1, row + thumb_rows - 1):
            move_cursor(inner_row, column)
            write(" ")
            move_cursor(inner_row, column + thumb_cols - 1)
            write(" ")
        clear_rect(row + thumb_rows - 1, column, thumb_cols, 1)
    move_cursor(row + thumb_rows, column)
    write(" " * thumb_cols)


def draw_cell_overlay(image_path: Path, index: int, selected_page_index: int, marked_paths, view, repaint_image: bool = False):
    grid_columns = view["grid_columns"]
    thumb_cols = view["thumb_cols"]
    thumb_rows = view["thumb_rows"]
    canvas_width = view["canvas_width"]
    canvas_height = view["canvas_height"]
    row, column = cell_position(index, grid_columns, thumb_cols, thumb_rows)
    is_marked = str(image_path) in marked_paths

    if repaint_image:
        thumb_path = ensure_thumbnail(image_path, canvas_width, canvas_height)
        if thumb_path is not None:
            kitty_image(thumb_path, row, column, thumb_cols, thumb_rows)

    clear_cell_overlay(row, column, thumb_cols, thumb_rows)

    if is_marked and index != selected_page_index:
        draw_mark_frame(row, column, thumb_cols, thumb_rows)
        move_cursor(row + thumb_rows, column)

    if index == selected_page_index:
        draw_selection_frame(row, column, thumb_cols, thumb_rows)
        move_cursor(row + thumb_rows, column)
        display = marked_label(image_path.name, thumb_cols, is_marked)
        write(f"{SELECTED_STYLE}{display[:thumb_cols]:<{thumb_cols}}{RESET}")
    else:
        move_cursor(row + thumb_rows, column)
        display = marked_label(image_path.name, thumb_cols, is_marked)
        if is_marked:
            write(f"{MARKED_STYLE}{display[:thumb_cols]:<{thumb_cols}}{RESET}")
        else:
            write(display[:thumb_cols].ljust(thumb_cols))


def page_geometry():
    size = shutil.get_terminal_size(fallback=(120, 40))
    usable_lines = max(1, size.lines - FOOTER_LINES - TOP_MARGIN)

    columns = max(1, min(MAX_GRID_COLUMNS, (size.columns + GAP_X) // (PREFERRED_CELL_WIDTH + GAP_X)))
    thumb_cols = max(1, (size.columns - GAP_X * (columns - 1)) // columns)

    while columns > 1 and thumb_cols < MIN_THUMB_COLS:
        columns -= 1
        thumb_cols = max(1, (size.columns - GAP_X * (columns - 1)) // columns)

    thumb_cols = clamp(thumb_cols, MIN_THUMB_COLS, MAX_THUMB_COLS)
    thumb_rows = clamp(round(thumb_cols * 0.55), 5, 12)
    cell_height = thumb_rows + LABEL_LINES + GAP_Y
    rows = max(1, (usable_lines + GAP_Y) // cell_height)
    canvas_width = clamp(thumb_cols * CELL_PIXEL_WIDTH, 240, THUMB_MAX_EDGE)
    canvas_height = clamp(thumb_rows * CELL_PIXEL_HEIGHT, 240, THUMB_MAX_EDGE)
    return size.columns, size.lines, columns, rows, thumb_cols, thumb_rows, canvas_width, canvas_height


def compute_grid_view(images, selected_index: int, viewport_row_start: int):
    total_columns, total_lines, grid_columns, grid_rows, thumb_cols, thumb_rows, canvas_width, canvas_height = page_geometry()
    page_size = max(1, grid_columns * grid_rows)
    total_rows = max(1, (len(images) + grid_columns - 1) // grid_columns)
    selected_index = clamp(selected_index, 0, len(images) - 1)
    selected_row_index = selected_index // grid_columns
    viewport_row_start = clamp(viewport_row_start, 0, max(0, total_rows - grid_rows))

    if selected_row_index < viewport_row_start:
        viewport_row_start = selected_row_index
    elif selected_row_index >= viewport_row_start + grid_rows:
        viewport_row_start = selected_row_index - grid_rows + 1

    start = viewport_row_start * grid_columns
    page_items = images[start:start + page_size]

    return {
        "total_columns": total_columns,
        "total_lines": total_lines,
        "grid_columns": grid_columns,
        "grid_rows": grid_rows,
        "thumb_cols": thumb_cols,
        "thumb_rows": thumb_rows,
        "canvas_width": canvas_width,
        "canvas_height": canvas_height,
        "page_size": page_size,
        "viewport_row_start": viewport_row_start,
        "start": start,
        "page_items": page_items,
        "selected_index": selected_index,
        "selected_page_index": selected_index - start,
    }


def grid_view_signature(view):
    return (
        view["total_columns"],
        view["total_lines"],
        view["grid_columns"],
        view["grid_rows"],
        view["thumb_cols"],
        view["thumb_rows"],
        view["canvas_width"],
        view["canvas_height"],
        view["viewport_row_start"],
        view["start"],
    )


def status_line(mode_label: str, source_label: str, total_images: int, show_marked_only: bool):
    filter_text = "  Filter Marked" if show_marked_only else ""
    return f"Gallery  Mode {mode_label}  {source_label}  {total_images} images{filter_text}"


def range_line(shown_start: int, shown_end: int, total_images: int, grid_columns: int, grid_rows: int):
    return f"Showing {shown_start}-{shown_end}/{total_images}  Grid {grid_columns}x{grid_rows}"


def controls_line():
    return "Controls  Arrows/hjkl move  gg/G home/end  Space mark  m marked-only  n jump forward  p/Backspace jump back  q/Esc quit"


def selection_line(selected_path: Path, selected_index: int, total_images: int):
    return f"Selected  {selected_index + 1}/{total_images}  {selected_path.name}"


def single_controls_line():
    return "View  Left/Right/h/l previous/next  Space mark  Enter/Esc/q back to grid"


def write_selection_result(result_file: Path, selected_paths):
    try:
        result_file.write_text("\n".join(selected_paths), encoding="utf-8")
    except OSError:
        pass


def write_focus_result(focus_file: Path, focused_path: Path):
    try:
        focus_file.write_text(str(focused_path), encoding="utf-8")
    except OSError:
        pass


def read_key(fd: int):
    ch = os.read(fd, 1)
    if not ch:
        return "EOF"
    if ch != b"\x1b":
        try:
            decoded = ch.decode("utf-8", errors="ignore")
            if decoded == "g":
                if select.select([fd], [], [], 0.18)[0]:
                    next_char = os.read(fd, 1).decode("utf-8", errors="ignore")
                    if next_char == "g":
                        return "GG"
                    return next_char or decoded
                return decoded
            return decoded
        except Exception:
            return ""

    if not select.select([fd], [], [], 0.03)[0]:
        return "ESC"

    seq = ch + os.read(fd, 1)
    if seq == b"\x1b[" and select.select([fd], [], [], 0.03)[0]:
        seq += os.read(fd, 1)
        if seq == b"\x1b[C":
            return "RIGHT"
        if seq == b"\x1b[D":
            return "LEFT"
        if seq == b"\x1b[A":
            return "UP"
        if seq == b"\x1b[B":
            return "DOWN"
        if seq.endswith(b"5") and select.select([fd], [], [], 0.03)[0]:
            seq += os.read(fd, 1)
            if seq == b"\x1b[5~":
                return "PAGEUP"
        if seq.endswith(b"6") and select.select([fd], [], [], 0.03)[0]:
            seq += os.read(fd, 1)
            if seq == b"\x1b[6~":
                return "PAGEDOWN"
    return "ESC"


class RawTerminal:
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.original = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        return self.fd

    def __exit__(self, exc_type, exc, tb):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.original)


def render_page(mode_label: str, source_label: str, images, marked_paths, show_marked_only: bool, view, redraw_images: bool, previous_view=None, previous_marked_paths=None):
    total_columns = view["total_columns"]
    total_lines = view["total_lines"]
    grid_columns = view["grid_columns"]
    grid_rows = view["grid_rows"]
    thumb_cols = view["thumb_cols"]
    thumb_rows = view["thumb_rows"]
    canvas_width = view["canvas_width"]
    canvas_height = view["canvas_height"]
    page_size = view["page_size"]
    start = view["start"]
    page_items = view["page_items"]
    selected_index = view["selected_index"]
    selected_page_index = view["selected_page_index"]

    can_incremental = (
        not redraw_images
        and previous_view is not None
        and previous_marked_paths is not None
        and previous_view["start"] == start
        and previous_view["page_items"] == page_items
    )

    if redraw_images:
        clear_images()
        clear_screen()
        hide_cursor()

    if redraw_images:
        for index, image_path in enumerate(page_items):
            row = TOP_MARGIN + 1 + (index // grid_columns) * (thumb_rows + LABEL_LINES + GAP_Y)
            column = 1 + (index % grid_columns) * (thumb_cols + GAP_X)
            thumb_path = ensure_thumbnail(image_path, canvas_width, canvas_height)
            if thumb_path is None:
                continue
            kitty_image(thumb_path, row, column, thumb_cols, thumb_rows)
            draw_cell_overlay(image_path, index, selected_page_index, marked_paths, view)
    elif can_incremental:
        hide_cursor()
        changed_indices = set()
        changed_indices.add(previous_view["selected_page_index"])
        changed_indices.add(selected_page_index)

        for index, image_path in enumerate(page_items):
            old_marked = str(image_path) in previous_marked_paths
            new_marked = str(image_path) in marked_paths
            if old_marked != new_marked:
                changed_indices.add(index)

        for index in sorted(changed_indices):
            if 0 <= index < len(page_items):
                draw_cell_overlay(page_items[index], index, selected_page_index, marked_paths, view, repaint_image=True)
    else:
        clear_screen()
        hide_cursor()
        for index, image_path in enumerate(page_items):
            draw_cell_overlay(image_path, index, selected_page_index, marked_paths, view, repaint_image=True)

    status_row = max(1, total_lines - 3)
    page_row = max(1, total_lines - 2)
    selected_row = max(1, total_lines - 1)
    controls_row = max(1, total_lines)
    shown_start = start + 1
    shown_end = start + len(page_items)

    move_cursor(status_row, 1)
    write(status_line(mode_label, source_label, len(images), show_marked_only).ljust(total_columns)[:total_columns])
    move_cursor(page_row, 1)
    write(range_line(shown_start, shown_end, len(images), grid_columns, grid_rows).ljust(total_columns)[:total_columns])
    move_cursor(selected_row, 1)
    selected_text = truncate_middle(
        selection_line(images[selected_index], selected_index, len(images)) + f"  Marked {len(marked_paths)}",
        total_columns,
    )
    write(f"{SELECTED_STYLE}{selected_text.ljust(total_columns)[:total_columns]}{RESET}")
    move_cursor(controls_row, 1)
    write(controls_line().ljust(total_columns)[:total_columns])
    flush()

    return selected_index, view["viewport_row_start"], page_size, grid_columns, canvas_width, canvas_height


def render_single_view(mode_label: str, source_label: str, images, selected_index: int, marked_paths, show_marked_only: bool):
    total_columns, total_lines = shutil.get_terminal_size(fallback=(120, 40))
    selected_index = clamp(selected_index, 0, len(images) - 1)
    image_path = images[selected_index]
    image_rows = max(4, total_lines - 4)
    image_cols = max(20, total_columns)
    display_cols, display_rows = fit_image_cells(image_path, image_cols, image_rows)
    canvas_width = clamp(display_cols * CELL_PIXEL_WIDTH, 640, FULL_MAX_EDGE)
    canvas_height = clamp(display_rows * CELL_PIXEL_HEIGHT, 480, FULL_MAX_EDGE)

    thumb_path = ensure_thumbnail(image_path, canvas_width, canvas_height)

    clear_images()
    clear_screen()
    hide_cursor()

    if thumb_path is not None:
        top_row = max(1, 1 + (image_rows - display_rows) // 2)
        left_col = max(1, 1 + (image_cols - display_cols) // 2)
        kitty_image(thumb_path, top_row, left_col, display_cols, display_rows)

    status_row = max(1, total_lines - 3)
    meta_row = max(1, total_lines - 2)
    detail_row = max(1, total_lines - 1)
    controls_row = max(1, total_lines)
    marked = "Marked" if str(image_path) in marked_paths else "Unmarked"
    marked_style = MARKED_STYLE if marked == "Marked" else UNMARKED_STYLE
    width, height = image_dimensions(str(image_path))
    dimensions = f"{width}x{height}" if width and height else "Unknown size"
    image_format = image_path.suffix.lstrip(".").upper() or "Unknown"

    try:
        file_size = format_bytes(image_path.stat().st_size)
        modified_at = format_timestamp(image_path.stat().st_mtime)
    except OSError:
        file_size = "Unknown size"
        modified_at = "Unknown time"

    move_cursor(status_row, 1)
    status = truncate_middle(
        f"View  Mode {mode_label}  {source_label}  {selected_index + 1}/{len(images)}"
        + ("  Filter Marked" if show_marked_only else ""),
        total_columns,
    )
    mark_badge = f"{marked_style}{marked}{RESET}"
    status_text = f"{ACCENT_STYLE}{status}{RESET}  {mark_badge}"
    write(pad_visible(status_text, total_columns)[: total_columns + 32])

    move_cursor(meta_row, 1)
    meta = truncate_middle(f"Info  {dimensions}  {file_size}  {image_format}  {modified_at}", total_columns)
    meta_text = f"{MUTED_STYLE}{meta}{RESET}"
    write(pad_visible(meta_text, total_columns)[: total_columns + 32])

    move_cursor(detail_row, 1)
    detail = truncate_middle(image_path.name, total_columns)
    write(f"{SELECTED_STYLE}{detail.ljust(total_columns)[:total_columns]}{RESET}")

    move_cursor(controls_row, 1)
    write(single_controls_line().ljust(total_columns)[:total_columns])
    flush()


def cleanup():
    clear_images()
    clear_screen()
    show_cursor()
    flush()


def main():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Gallery requires an interactive terminal.", file=sys.stderr)
        return 1

    mode_label, source_label, all_images, start_image, initial_marked = resolve_gallery_inputs(sys.argv)
    if mode_label is None:
        return 0

    if not all_images:
        return 0

    selected_index = 0
    if start_image is not None:
        try:
            selected_index = all_images.index(start_image)
        except ValueError:
            selected_index = 0

    marked_paths = set(initial_marked)
    all_positions = {str(image_path): index for index, image_path in enumerate(all_images)}
    selected_path = all_images[selected_index]
    show_marked_only = False
    result_file = Path(sys.argv[3]).expanduser() if len(sys.argv) > 3 and sys.argv[3] else None
    focus_file = Path(sys.argv[4]).expanduser() if len(sys.argv) > 4 and sys.argv[4] else None

    try:
        with RawTerminal() as fd:
            preload_thread = None
            mode = "grid"
            viewport_row_start = 0
            last_mode = None
            last_grid_signature = None
            last_preload_signature = None
            previous_view = None
            previous_marked_paths = None
            while True:
                images = build_visible_images(all_images, marked_paths, show_marked_only)
                if show_marked_only and not images:
                    show_marked_only = False
                    images = list(all_images)

                selected_path, selected_index = resolve_selected_image(all_images, all_positions, images, selected_path)

                if mode == "grid":
                    view = compute_grid_view(images, selected_index, viewport_row_start)
                    redraw_images = last_mode != "grid" or last_grid_signature != grid_view_signature(view)
                    selected_index, viewport_row_start, page_size, grid_columns, canvas_width, canvas_height = render_page(
                        mode_label, source_label, images, marked_paths, show_marked_only, view, redraw_images, previous_view, previous_marked_paths
                    )
                    last_grid_signature = grid_view_signature(view)
                    last_mode = "grid"
                    previous_view = view
                    previous_marked_paths = set(marked_paths)

                    preload_signature = (
                        view["viewport_row_start"],
                        grid_columns,
                        canvas_width,
                        canvas_height,
                    )
                    preload_paths = row_image_paths(
                        images,
                        view["viewport_row_start"] + view["grid_rows"],
                        PRELOAD_ROWS,
                        grid_columns,
                    ) + row_image_paths(
                        images,
                        max(0, view["viewport_row_start"] - PRELOAD_ROWS),
                        min(PRELOAD_ROWS, view["viewport_row_start"]),
                        grid_columns,
                    )

                    if (
                        preload_paths
                        and preload_signature != last_preload_signature
                        and (preload_thread is None or not preload_thread.is_alive())
                    ):
                        preload_thread = threading.Thread(
                            target=preload_thumbnails,
                            args=(preload_paths, canvas_width, canvas_height),
                            daemon=True,
                        )
                        preload_thread.start()
                        last_preload_signature = preload_signature
                else:
                    render_single_view(mode_label, source_label, images, selected_index, marked_paths, show_marked_only)
                    last_mode = "single"
                    last_grid_signature = None
                    previous_view = None
                    previous_marked_paths = None

                key = read_key(fd)

                if key in {"q", "Q", "ESC", "EOF"}:
                    if mode == "single" and key != "Q":
                        mode = "grid"
                        continue
                    break
                if key in {"\r", "\n"}:
                    if mode == "grid":
                        mode = "single"
                    else:
                        mode = "grid"
                    continue
                if key == " ":
                    current = str(images[selected_index])
                    if current in marked_paths:
                        marked_paths.remove(current)
                    else:
                        marked_paths.add(current)
                    selected_path = images[selected_index]
                    previous_marked_paths = None
                    continue
                if key in {"m", "M"}:
                    if show_marked_only:
                        show_marked_only = False
                    elif marked_paths:
                        show_marked_only = True
                    selected_path = images[selected_index]
                    previous_view = None
                    continue
                if key in {"RIGHT", "l"}:
                    if selected_index + 1 < len(images):
                        selected_index += 1
                        selected_path = images[selected_index]
                    continue
                if key in {"LEFT", "h"}:
                    if selected_index > 0:
                        selected_index -= 1
                        selected_path = images[selected_index]
                    continue
                if mode == "single":
                    continue
                if key in {"UP", "k"}:
                    candidate = selected_index - grid_columns
                    if candidate >= 0:
                        selected_index = candidate
                        selected_path = images[selected_index]
                    continue
                if key in {"DOWN", "j"}:
                    candidate = selected_index + grid_columns
                    if candidate < len(images):
                        selected_index = candidate
                        selected_path = images[selected_index]
                    continue
                if key in {"n", "PAGEDOWN"}:
                    selected_index = min(len(images) - 1, selected_index + page_size)
                    selected_path = images[selected_index]
                    continue
                if key in {"p", "PAGEUP", "\x7f"}:
                    selected_index = max(0, selected_index - page_size)
                    selected_path = images[selected_index]
                    continue
                if key == "GG":
                    selected_index = 0
                    selected_path = images[selected_index]
                    continue
                if key == "G":
                    selected_index = len(images) - 1
                    selected_path = images[selected_index]
                    continue
    finally:
        cleanup()

    if result_file is not None:
        write_selection_result(result_file, sorted(marked_paths))
    if focus_file is not None and images:
        write_focus_result(focus_file, images[selected_index])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

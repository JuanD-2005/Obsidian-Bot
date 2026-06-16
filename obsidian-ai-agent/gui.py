"""
gui.py
------
Obsidian AI Agent — Floating GUI popup.

A minimal dark-themed window intended to be launched via a global hotkey
(configured externally in your DE/WM).  The user types raw text, hits
Alt+Enter (or clicks "Procesar"), and the agent routes + generates the note.

Architecture
------------
The Tkinter main loop MUST stay on the main thread.  The agent pipeline
(router → LLM → file write) runs in a daemon Thread so the UI never freezes.
Thread → main-thread communication is done via a thread-safe queue that the
main loop polls every 100 ms with `after()`.

Launch
------
    python gui.py
    # or, once installed:
    obsidian-gui
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from typing import Callable

# --- INYECCIÓN DEL ENTORNO ---
from dotenv import load_dotenv

# Calculamos la ruta absoluta de la carpeta del proyecto
BASE_DIR = Path(__file__).resolve().parent

# Forzamos la carga del archivo .env antes de arrancar la aplicación
load_dotenv(BASE_DIR / ".env")
# -----------------------------

# ---------------------------------------------------------------------------
# Theme tokens — change here to restyle everything
# ---------------------------------------------------------------------------
COLORS = {
    "bg":           "#1e1e2e",   # main background (Catppuccin Mocha base)
    "surface":      "#313244",   # text area background
    "border":       "#45475a",   # subtle border
    "accent":       "#89b4fa",   # blue accent (buttons, focus ring)
    "accent_hover": "#74c7ec",   # lighter blue on hover
    "btn_bg":       "#45475a",   # button normal background
    "btn_active":   "#585b70",   # button pressed
    "text":         "#cdd6f4",   # primary text
    "subtext":      "#a6adc8",   # placeholder / hint text
    "success":      "#a6e3a1",   # green — success state
    "error_bg":     "#f38ba8",   # red — error background
    "error_text":   "#1e1e2e",   # text on red
    "processing":   "#fab387",   # orange — working state
}

FONT_FAMILY = "JetBrains Mono"   # falls back to system monospace if absent
FONT_SIZE_NORMAL = 12
FONT_SIZE_SMALL  = 10
FONT_SIZE_TITLE  = 11

WINDOW_WIDTH  = 560
WINDOW_HEIGHT = 320
PADDING       = 16


# ---------------------------------------------------------------------------
# Pipeline worker (runs in background thread)
# ---------------------------------------------------------------------------

def _run_pipeline(raw_text: str, result_queue: "queue.Queue[dict]") -> None:
    """
    Execute the full agent pipeline and push the result into *result_queue*.

    The queue always receives a dict with key "ok" (bool).
    On success: {"ok": True,  "path": Path}
    On failure: {"ok": False, "error": str}
    """
    try:
        from agent import file_manager
        from agent.providers import get_provider
        from agent.router import route
        from agent.config import settings

        # 1. Route — find template + destination
        route_result = route(raw_text)

        # 2. Load template content
        template_content = file_manager.read_template(route_result.template_name)

        # 3. Generate note via LLM
        llm = get_provider(settings.default_ai_provider)
        generated_md = llm.generate(template_content, raw_text)

        # 4. Write to vault
        output_path = file_manager.write_note(
            generated_md,
            topic=route_result.template_name,
            destination=route_result.destination,
        )

        result_queue.put({"ok": True, "path": output_path})

    except Exception as exc:  # noqa: BLE001
        result_queue.put({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class AgentWindow:
    """
    The floating popup window.

    Lifecycle
    ---------
    1. User opens window.
    2. Types text in the textarea.
    3. Submits via Alt+Enter or "Procesar" button.
    4. UI enters "processing" state (button disabled, status label updated).
    5. Background thread runs the pipeline, puts result in queue.
    6. `_poll_queue()` picks up the result on the main thread.
    7a. Success → brief "✓ Guardado" flash, then window closes.
    7b. Error   → red status label + error popup; window stays open for retry.
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._queue: queue.Queue[dict] = queue.Queue()
        self._poll_job: str | None = None

        self._setup_window()
        self._setup_fonts()
        self._build_ui()
        self._bind_shortcuts()

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.root.title("Obsidian AI Agent")
        self.root.configure(bg=COLORS["bg"])
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)     # float above other windows

        # Remove default title bar decorations on supported platforms
        # (keeps a thin border for drag-to-move)
        self.root.overrideredirect(False)          # set True for fully borderless

        # Center on screen
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - WINDOW_WIDTH)  // 2
        y  = (sh - WINDOW_HEIGHT) // 2
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")

    def _setup_fonts(self) -> None:
        available = tkfont.families()
        family = FONT_FAMILY if FONT_FAMILY in available else "Monospace"

        self.font_normal = tkfont.Font(family=family, size=FONT_SIZE_NORMAL)
        self.font_small  = tkfont.Font(family=family, size=FONT_SIZE_SMALL)
        self.font_title  = tkfont.Font(family=family, size=FONT_SIZE_TITLE, weight="bold")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        p = PADDING

        # ── Outer frame ──────────────────────────────────────────────
        outer = tk.Frame(self.root, bg=COLORS["bg"], padx=p, pady=p)
        outer.pack(fill="both", expand=True)

        # ── Title row ────────────────────────────────────────────────
        title_row = tk.Frame(outer, bg=COLORS["bg"])
        title_row.pack(fill="x", pady=(0, 10))

        tk.Label(
            title_row,
            text="⬡  Obsidian AI Agent",
            bg=COLORS["bg"],
            fg=COLORS["accent"],
            font=self.font_title,
            anchor="w",
        ).pack(side="left")

        tk.Button(
            title_row,
            text="✕",
            bg=COLORS["bg"],
            fg=COLORS["subtext"],
            activebackground=COLORS["bg"],
            activeforeground=COLORS["text"],
            relief="flat",
            bd=0,
            font=self.font_small,
            cursor="hand2",
            command=self.root.destroy,
        ).pack(side="right")

        # ── Textarea with border frame ────────────────────────────────
        border_frame = tk.Frame(outer, bg=COLORS["border"], padx=1, pady=1)
        border_frame.pack(fill="both", expand=True, pady=(0, 10))

        self.textarea = tk.Text(
            border_frame,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            insertbackground=COLORS["accent"],
            selectbackground=COLORS["accent"],
            selectforeground=COLORS["bg"],
            font=self.font_normal,
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            wrap="word",
            undo=True,
        )
        self.textarea.pack(fill="both", expand=True)
        self.textarea.focus_set()

        # Placeholder behaviour
        self._placeholder = "Describe tu nota... (Alt+Enter para enviar)"
        self._show_placeholder()
        self.textarea.bind("<FocusIn>",  self._on_focus_in)
        self.textarea.bind("<FocusOut>", self._on_focus_out)

        # ── Bottom row: status label + button ────────────────────────
        bottom = tk.Frame(outer, bg=COLORS["bg"])
        bottom.pack(fill="x")

        self.status_label = tk.Label(
            bottom,
            text="Alt+Enter para enviar",
            bg=COLORS["bg"],
            fg=COLORS["subtext"],
            font=self.font_small,
            anchor="w",
        )
        self.status_label.pack(side="left")

        self.btn = _HoverButton(
            bottom,
            text="Procesar  ⏎",
            font=self.font_small,
            bg=COLORS["btn_bg"],
            fg=COLORS["text"],
            activebackground=COLORS["btn_active"],
            activeforeground=COLORS["text"],
            hover_bg=COLORS["accent"],
            hover_fg=COLORS["bg"],
            relief="flat",
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2",
            command=self._on_submit,
        )
        self.btn.pack(side="right")

    # ------------------------------------------------------------------
    # Placeholder helpers
    # ------------------------------------------------------------------

    def _show_placeholder(self) -> None:
        self.textarea.insert("1.0", self._placeholder)
        self.textarea.config(fg=COLORS["subtext"])
        self._has_placeholder = True

    def _hide_placeholder(self) -> None:
        if getattr(self, "_has_placeholder", False):
            self.textarea.delete("1.0", "end")
            self.textarea.config(fg=COLORS["text"])
            self._has_placeholder = False

    def _on_focus_in(self, _event: tk.Event) -> None:
        self._hide_placeholder()

    def _on_focus_out(self, _event: tk.Event) -> None:
        if not self.textarea.get("1.0", "end-1c").strip():
            self._show_placeholder()

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def _bind_shortcuts(self) -> None:
        # Alt+Enter to submit (works on Linux/Mac; Windows may need <Alt_L><Return>)
        self.textarea.bind("<Alt-Return>", lambda e: self._on_submit())
        # Escape to close
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    # ------------------------------------------------------------------
    # Submit handler
    # ------------------------------------------------------------------

    def _on_submit(self) -> None:
        raw_text = self.textarea.get("1.0", "end-1c").strip()

        if not raw_text or raw_text == self._placeholder:
            self._set_status("Escribe algo primero.", color=COLORS["error_bg"])
            return

        self._set_processing_state(True)
        self._set_status("Procesando con IA...", color=COLORS["processing"])

        # Kick off the background thread
        thread = threading.Thread(
            target=_run_pipeline,
            args=(raw_text, self._queue),
            daemon=True,
        )
        thread.start()

        # Start polling the queue
        self._poll_queue()

    # ------------------------------------------------------------------
    # Queue polling (main thread)
    # ------------------------------------------------------------------

    def _poll_queue(self) -> None:
        """Check the result queue every 100 ms without blocking the UI."""
        try:
            result = self._queue.get_nowait()
        except queue.Empty:
            # Nothing yet — schedule next check
            self._poll_job = self.root.after(100, self._poll_queue)
            return

        # Got a result
        if result["ok"]:
            self._on_success(result["path"])
        else:
            self._on_error(result["error"])

    # ------------------------------------------------------------------
    # Result handlers
    # ------------------------------------------------------------------

    def _on_success(self, path: Path) -> None:
        short_path = f"…/{path.parent.name}/{path.name}"
        self._set_status(f"✓ Guardado en {short_path}", color=COLORS["success"])
        # Close the window after a short visual confirmation delay
        self.root.after(1400, self.root.destroy)

    def _on_error(self, error_msg: str) -> None:
        self._set_processing_state(False)
        self._set_status("Error — ver detalles", color=COLORS["error_bg"])
        _ErrorPopup(self.root, error_msg)

    # ------------------------------------------------------------------
    # UI state helpers
    # ------------------------------------------------------------------

    def _set_processing_state(self, processing: bool) -> None:
        state = "disabled" if processing else "normal"
        self.btn.config(state=state)
        self.textarea.config(state=state)

    def _set_status(self, message: str, color: str = "") -> None:
        self.status_label.config(
            text=message,
            fg=color or COLORS["subtext"],
        )


# ---------------------------------------------------------------------------
# Helper widgets
# ---------------------------------------------------------------------------

class _HoverButton(tk.Button):
    """A tk.Button that changes color on mouse enter/leave."""

    def __init__(self, master: tk.Widget, hover_bg: str, hover_fg: str, **kwargs) -> None:
        self._normal_bg = kwargs.get("bg", "#ffffff")
        self._normal_fg = kwargs.get("fg", "#000000")
        self._hover_bg  = hover_bg
        self._hover_fg  = hover_fg
        super().__init__(master, **kwargs)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _e: tk.Event) -> None:
        if str(self.cget("state")) != "disabled":
            self.config(bg=self._hover_bg, fg=self._hover_fg)

    def _on_leave(self, _e: tk.Event) -> None:
        self.config(bg=self._normal_bg, fg=self._normal_fg)


class _ErrorPopup:
    """Small modal popup that shows an error message."""

    def __init__(self, parent: tk.Tk, message: str) -> None:
        top = tk.Toplevel(parent)
        top.title("Error")
        top.configure(bg=COLORS["bg"])
        top.resizable(False, False)
        top.attributes("-topmost", True)
        top.grab_set()   # modal

        # Center relative to parent
        parent.update_idletasks()
        px = parent.winfo_x()
        py = parent.winfo_y()
        pw = parent.winfo_width()
        top.geometry(f"460x220+{px + (pw - 460) // 2}+{py + 60}")

        f = tk.Frame(top, bg=COLORS["bg"], padx=20, pady=16)
        f.pack(fill="both", expand=True)

        tk.Label(
            f,
            text="⚠  Algo salió mal",
            bg=COLORS["bg"],
            fg=COLORS["error_bg"],
            font=tkfont.Font(family="Monospace", size=11, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 10))

        # Scrollable error text
        frame_text = tk.Frame(f, bg=COLORS["border"], padx=1, pady=1)
        frame_text.pack(fill="both", expand=True, pady=(0, 12))

        txt = tk.Text(
            frame_text,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=tkfont.Font(family="Monospace", size=9),
            relief="flat",
            bd=0,
            padx=8,
            pady=6,
            wrap="word",
            height=6,
        )
        txt.insert("1.0", message)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True)

        _HoverButton(
            f,
            text="Cerrar",
            bg=COLORS["btn_bg"],
            fg=COLORS["text"],
            activebackground=COLORS["btn_active"],
            activeforeground=COLORS["text"],
            hover_bg=COLORS["accent"],
            hover_fg=COLORS["bg"],
            relief="flat",
            bd=0,
            padx=14,
            pady=5,
            cursor="hand2",
            font=tkfont.Font(family="Monospace", size=10),
            command=top.destroy,
        ).pack(side="right")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def launch() -> None:
    """Create the Tk root and start the main loop."""
    root = tk.Tk()
    AgentWindow(root)
    root.mainloop()


if __name__ == "__main__":
    launch()
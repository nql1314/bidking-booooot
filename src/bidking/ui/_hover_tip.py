"""通用控件悬浮说明。"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional, Union

TextSource = Union[str, Callable[[], str]]


class LabelHoverTip:
    """在控件上短暂停留后显示说明文字（用于配置项 label 等）。"""

    def __init__(
        self,
        widget: tk.Widget,
        text: TextSource,
        *,
        delay_ms: int = 380,
        wraplength: int = 480,
    ) -> None:
        self.widget = widget
        self._text = text
        self.delay_ms = delay_ms
        self.wraplength = wraplength
        self._tip: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _resolve_text(self) -> str:
        try:
            raw = self._text() if callable(self._text) else self._text
        except Exception:
            raw = ""
        return (raw or "").strip()

    def _cancel_sched(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _schedule(self, _event: object = None) -> None:
        self._cancel_sched()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _hide(self, _event: object = None) -> None:
        self._cancel_sched()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _show(self) -> None:
        self._after_id = None
        text = self._resolve_text()
        if not text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        try:
            tw.wm_attributes("-topmost", True)
        except Exception:
            pass
        tw.geometry(f"+{x}+{y}")
        tk.Label(
            tw,
            text=text,
            justify="left",
            bg="#fffacd",
            fg="#1a1a2e",
            relief="solid",
            borderwidth=1,
            font=("微软雅黑", 9),
            wraplength=self.wraplength,
            padx=10,
            pady=8,
        ).pack()
        self._tip = tw

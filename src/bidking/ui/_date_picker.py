# -*- coding: utf-8 -*-
"""Tk 日期/日期时间选择框（只读输入 + 日历弹窗）。"""

from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date, datetime
from tkinter import ttk


class DatePicker(ttk.Frame):
    """只读日期框；值为 ``YYYY-MM-DD`` 或 ``YYYY-MM-DD HH:MM``（含时分时）。"""

    def __init__(
        self,
        master: tk.Misc,
        *,
        textvariable: tk.StringVar | None = None,
        width: int = 11,
        include_time: bool = False,
        default_hour: int = 0,
        default_minute: int = 0,
        **kwargs: object,
    ) -> None:
        super().__init__(master, **kwargs)
        self._include_time = include_time
        self._default_hour = default_hour
        self._default_minute = default_minute
        self._var = textvariable if textvariable is not None else tk.StringVar()
        entry_width = width if width != 11 else (17 if include_time else 11)
        self._entry = ttk.Entry(self, textvariable=self._var, width=entry_width, state="readonly")
        self._entry.pack(side=tk.LEFT)
        ttk.Button(self, text="选择", width=5, command=self._open_picker).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        ttk.Button(self, text="清除", width=5, command=self.clear).pack(side=tk.LEFT, padx=(2, 0))

    @property
    def textvariable(self) -> tk.StringVar:
        return self._var

    def get(self) -> str:
        return self._var.get().strip()

    def set(self, value: str) -> None:
        self._var.set((value or "").strip())

    def clear(self) -> None:
        self._var.set("")

    def _open_picker(self) -> None:
        initial = _parse_datetime(self.get())
        _PickerPopup(
            self.winfo_toplevel(),
            initial=initial,
            include_time=self._include_time,
            default_hour=self._default_hour,
            default_minute=self._default_minute,
            on_select=self.set,
        )


def _parse_datetime(text: str) -> datetime | None:
    s = (text or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


class _PickerPopup(tk.Toplevel):
    _WEEKDAYS = ("一", "二", "三", "四", "五", "六", "日")

    def __init__(
        self,
        parent: tk.Misc,
        *,
        initial: datetime | None,
        include_time: bool,
        default_hour: int,
        default_minute: int,
        on_select: object,
    ) -> None:
        super().__init__(parent)
        self._on_select = on_select
        self._include_time = include_time
        now = datetime.now()
        base = initial or now
        self._year = base.year
        self._month = base.month
        self._selected_day: int | None = base.day

        if initial is not None:
            hour, minute = initial.hour, initial.minute
        else:
            hour, minute = default_hour, default_minute

        self.title("选择日期时间" if include_time else "选择日期")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        header = ttk.Frame(self, padding=6)
        header.pack(fill=tk.X)
        ttk.Button(header, text="◀", width=3, command=self._prev_month).pack(side=tk.LEFT)
        self._title_var = tk.StringVar()
        ttk.Label(header, textvariable=self._title_var, width=14, anchor=tk.CENTER).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(header, text="▶", width=3, command=self._next_month).pack(side=tk.LEFT)

        self._grid = ttk.Frame(self, padding=(6, 0, 6, 0))
        self._grid.pack()

        if include_time:
            f_time = ttk.Frame(self, padding=(6, 4, 6, 0))
            f_time.pack(fill=tk.X)
            ttk.Label(f_time, text="时分:").pack(side=tk.LEFT)
            self._hour_var = tk.StringVar(value=f"{hour:02d}")
            self._minute_var = tk.StringVar(value=f"{minute:02d}")
            tk.Spinbox(
                f_time,
                from_=0,
                to=23,
                width=3,
                textvariable=self._hour_var,
                wrap=True,
            ).pack(side=tk.LEFT, padx=(4, 2))
            ttk.Label(f_time, text=":").pack(side=tk.LEFT)
            tk.Spinbox(
                f_time,
                from_=0,
                to=59,
                width=3,
                textvariable=self._minute_var,
                wrap=True,
            ).pack(side=tk.LEFT, padx=(2, 0))

        footer = ttk.Frame(self, padding=6)
        footer.pack(fill=tk.X)
        ttk.Button(footer, text="今天", command=self._pick_now).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(footer, text="确定", command=self._confirm).pack(side=tk.LEFT, padx=4)
        ttk.Button(footer, text="取消", command=self.destroy).pack(side=tk.RIGHT)

        self._render()
        self.update_idletasks()
        px = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
        py = parent.winfo_rooty() + 80
        self.geometry(f"+{px}+{py}")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _prev_month(self) -> None:
        if self._month == 1:
            self._month = 12
            self._year -= 1
        else:
            self._month -= 1
        self._render()

    def _next_month(self) -> None:
        if self._month == 12:
            self._month = 1
            self._year += 1
        else:
            self._month += 1
        self._render()

    def _pick_now(self) -> None:
        now = datetime.now()
        if self._include_time:
            self._apply(now)
        else:
            self._apply(datetime(now.year, now.month, now.day))

    def _confirm(self) -> None:
        if self._selected_day is None:
            return
        picked = datetime(self._year, self._month, self._selected_day)
        if self._include_time:
            picked = picked.replace(
                hour=self._read_spin(self._hour_var, 0, 23),
                minute=self._read_spin(self._minute_var, 0, 59),
            )
        self._apply(picked)

    @staticmethod
    def _read_spin(var: tk.StringVar, lo: int, hi: int) -> int:
        try:
            v = int(var.get())
        except ValueError:
            return lo
        return max(lo, min(hi, v))

    def _apply(self, picked: datetime) -> None:
        if self._include_time:
            self._on_select(picked.strftime("%Y-%m-%d %H:%M"))
        else:
            self._on_select(picked.strftime("%Y-%m-%d"))
        self.destroy()

    def _select_day(self, day: int) -> None:
        self._selected_day = day
        if not self._include_time:
            self._apply(datetime(self._year, self._month, day))
            return
        self._render()

    def _render(self) -> None:
        self._title_var.set(f"{self._year}年 {self._month:02d}月")
        for child in self._grid.winfo_children():
            child.destroy()

        for col, wd in enumerate(self._WEEKDAYS):
            ttk.Label(self._grid, text=wd, width=4, anchor=tk.CENTER).grid(
                row=0, column=col, padx=1, pady=1
            )

        cal = calendar.Calendar(firstweekday=0)
        weeks = cal.monthdayscalendar(self._year, self._month)
        today = date.today()
        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week):
                if day == 0:
                    ttk.Label(self._grid, text="", width=4).grid(
                        row=row, column=col, padx=1, pady=1
                    )
                    continue
                cell = date(self._year, self._month, day)
                is_sel = self._selected_day == day
                is_today = today == cell
                label = str(day)
                if is_today and not is_sel:
                    label = f"{day}*"
                btn = ttk.Button(
                    self._grid,
                    text=label,
                    width=4,
                    command=lambda d=day: self._select_day(d),
                )
                btn.grid(row=row, column=col, padx=1, pady=1)

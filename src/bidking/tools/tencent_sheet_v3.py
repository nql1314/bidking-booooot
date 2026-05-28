"""腾讯文档在线表格 Open API V3 客户端（读范围 / batchUpdate 写、删行）。"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_A1_RANGE_RE = re.compile(
    r"^([A-Za-z]+)(\d+)(?::([A-Za-z]+)(\d+))?$",
)
_BATCH_REQUEST_LIMIT = 5


def parse_a1_range(range_a1: str) -> tuple[int, int, int, int]:
    """
    解析 A1 区域为 1-based 行列边界 (row_start, col_start, row_end, col_end)。

    支持 ``A4:E200`` 或 ``A4``（单格）。
    """
    raw = str(range_a1 or "").strip()
    if "!" in raw:
        raw = raw.split("!", 1)[1].strip()
    m = _A1_RANGE_RE.match(raw)
    if not m:
        raise ValueError(f"无效 A1 区域: {range_a1!r}")
    c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3), m.group(4)
    col_start = _col_letter_to_index(c1)
    row_start = r1
    if c2 is None:
        return row_start, col_start, row_start, col_start
    return row_start, col_start, int(r2), _col_letter_to_index(c2)


def _col_letter_to_index(col: str) -> int:
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _col_index_to_letter(index: int) -> str:
    if index < 1:
        raise ValueError(f"列索引须 >= 1，收到 {index}")
    letters: list[str] = []
    n = index
    while n:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def cell_value_to_text(cell: dict[str, Any] | None) -> str:
    """从 V3 ``gridData`` 单元格对象提取显示文本。"""
    if not isinstance(cell, dict):
        return ""
    cv = cell.get("cellValue")
    if not isinstance(cv, dict):
        return ""
    if cv.get("text") is not None:
        return str(cv["text"]).strip()
    if cv.get("number") is not None:
        n = cv["number"]
        if isinstance(n, float) and n.is_integer():
            return str(int(n))
        return str(n).strip()
    link = cv.get("link")
    if isinstance(link, dict) and link.get("text") is not None:
        return str(link["text"]).strip()
    return ""


def grid_data_to_rows(grid_data: dict[str, Any] | None) -> tuple[int, int, list[list[str]]]:
    """
  将 ``gridData`` 转为 ``(start_row_1based, start_col_1based, rows)``。

  API 的 ``startRow``/``startColumn`` 为 0-based。
  """
    if not isinstance(grid_data, dict):
        return 1, 1, []
    start_row = int(grid_data.get("startRow", 0)) + 1
    start_col = int(grid_data.get("startColumn", 0)) + 1
    out: list[list[str]] = []
    for row in grid_data.get("rows") or []:
        if not isinstance(row, dict):
            continue
        line = [cell_value_to_text(c) for c in row.get("values") or []]
        out.append(line)
    return start_row, start_col, out


def build_update_range_request(
    *,
    sheet_id: str,
    start_row_1based: int,
    start_col_1based: int,
    values: list[list[str]],
) -> dict[str, Any]:
    """构造 ``updateRangeRequest``（行列均为 1-based 入参，内部转 0-based）。"""
    rows_payload: list[dict[str, Any]] = []
    for line in values:
        rows_payload.append(
            {
                "values": [
                    {"cellValue": {"text": str(v)}}
                    for v in line
                ]
            }
        )
    return {
        "updateRangeRequest": {
            "sheetId": sheet_id,
            "gridData": {
                "startRow": max(0, int(start_row_1based) - 1),
                "startColumn": max(0, int(start_col_1based) - 1),
                "rows": rows_payload,
            },
        }
    }


def build_delete_rows_request(
    *,
    sheet_id: str,
    row_index_1based: int,
) -> dict[str, Any]:
    """删除工作表一行（``deleteDimensionRequest``，行号为 1-based）。"""
    idx = int(row_index_1based)
    return {
        "deleteDimensionRequest": {
            "sheetId": sheet_id,
            "dimension": "ROW",
            "startIndex": idx,
            "endIndex": idx + 1,
        }
    }


class TencentSheetV3Client:
    """腾讯文档在线表格 Open API V3。"""

    def __init__(
        self,
        *,
        file_id: str,
        client_id: str,
        open_id: str,
        access_token: str,
        timeout: float = 30.0,
    ) -> None:
        self.file_id = file_id.strip()
        self.client_id = client_id.strip()
        self.open_id = open_id.strip()
        self.access_token = access_token.strip()
        self.timeout = timeout
        if not all((self.file_id, self.client_id, self.open_id, self.access_token)):
            raise ValueError(
                "Open API V3 缺少 file_id / client_id / open_id / access_token"
            )

    @property
    def book_id(self) -> str:
        """与历史配置字段 ``book_id`` 同义，即 V3 ``fileId``。"""
        return self.file_id

    def _headers(self) -> dict[str, str]:
        return {
            "Access-Token": self.access_token,
            "Client-Id": self.client_id,
            "Open-Id": self.open_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"https://docs.qq.com{path}"
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers=self._headers(), method=method.upper()
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Open API V3 HTTP {exc.code}: {detail}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Open API V3 响应非 JSON: {raw[:200]}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Open API V3 响应格式异常: {payload!r}")
        ret = payload.get("ret", payload.get("code"))
        if ret not in (0, None, "0"):
            raise RuntimeError(
                f"Open API V3 业务失败 ret={ret} msg="
                f"{payload.get('msg') or payload.get('message')!r}"
            )
        return payload

    def get_range_grid(
        self,
        sheet_id: str,
        range_a1: str,
    ) -> tuple[int, int, list[list[str]]]:
        """读取区域，返回 ``(起始行 1-based, 起始列 1-based, 行数据)``。"""
        rng = str(range_a1 or "").strip()
        if "!" in rng:
            rng = rng.split("!", 1)[1].strip()
        path = (
            f"/openapi/spreadsheet/v3/files/{self.file_id}/"
            f"{urllib.parse.quote(sheet_id, safe='')}/"
            f"{urllib.parse.quote(rng, safe=':')}"
        )
        payload = self._request("GET", path)
        data = payload.get("data")
        grid = data.get("gridData") if isinstance(data, dict) else None
        if grid is None:
            grid = payload.get("gridData")
        return grid_data_to_rows(grid if isinstance(grid, dict) else None)

    def get_range_values(self, sheet_id: str, range_a1: str) -> list[list[str]]:
        """读取区域，仅返回相对区域内的行（不含绝对行号）。"""
        _, _, rows = self.get_range_grid(sheet_id, range_a1)
        return rows

    def batch_update(self, requests: list[dict[str, Any]]) -> None:
        """执行 batchUpdate，自动按每批最多 5 个 request 拆分。"""
        if not requests:
            return
        path = (
            f"/openapi/spreadsheet/v3/files/"
            f"{urllib.parse.quote(self.file_id, safe='$')}/batchUpdate"
        )
        for i in range(0, len(requests), _BATCH_REQUEST_LIMIT):
            chunk = requests[i : i + _BATCH_REQUEST_LIMIT]
            self._request("POST", path, body={"requests": chunk})

    def update_values(
        self,
        sheet_id: str,
        range_a1: str,
        values: list[list[str]],
    ) -> None:
        """写入矩形区域（单次 updateRangeRequest）。"""
        row_start, col_start, _, _ = parse_a1_range(range_a1)
        self.batch_update(
            [
                build_update_range_request(
                    sheet_id=sheet_id,
                    start_row_1based=row_start,
                    start_col_1based=col_start,
                    values=values,
                )
            ]
        )

    def update_range(self, range_a1: str, values: list[list[str]]) -> None:
        """兼容 ``sheetId!A1:B2`` 写法。"""
        sheet_id, rng = _split_sheet_range(range_a1)
        self.update_values(sheet_id, rng, values)

    def read_count_at_row(
        self,
        *,
        sheet_id: str,
        row_index: int,
        count_col: str,
        fallback: int = 0,
        parse_count: Any = None,
    ) -> int:
        range_a1 = f"{count_col}{row_index}"
        rows = self.get_range_values(sheet_id, range_a1)
        if rows and rows[0]:
            raw = str(rows[0][0]).strip()
            if parse_count is not None:
                return int(parse_count(raw))
            try:
                return max(0, int(float(raw.replace(",", ""))))
            except ValueError:
                return fallback
        return fallback

    def clear_temp_rows(
        self,
        *,
        sheet_id: str,
        row_indices: list[int],
        col_range: str,
    ) -> list[int]:
        """清空临时表指定行的列区间；失败行号写入返回值。"""
        if not row_indices:
            return []
        if ":" not in col_range:
            raise ValueError(f"col_range 须为 A:E 形式，收到 {col_range!r}")
        left, right = col_range.split(":", 1)
        col_count = _col_letter_to_index(right) - _col_letter_to_index(left) + 1
        blank = [""] * col_count
        failed: list[int] = []
        for row_index in sorted(row_indices, reverse=True):
            range_a1 = f"{left}{row_index}:{right}{row_index}"
            try:
                self.update_values(sheet_id, range_a1, [blank])
            except RuntimeError:
                failed.append(row_index)
        return failed

    def delete_rows(
        self,
        *,
        sheet_id: str,
        row_indices: list[int],
    ) -> list[int]:
        """按行删除（``deleteDimensionRequest``，1-based 行号）。"""
        failed: list[int] = []
        requests = [
            build_delete_rows_request(sheet_id=sheet_id, row_index_1based=row_index)
            for row_index in sorted(row_indices, reverse=True)
        ]
        for i in range(0, len(requests), _BATCH_REQUEST_LIMIT):
            chunk = requests[i : i + _BATCH_REQUEST_LIMIT]
            try:
                self.batch_update(chunk)
            except RuntimeError:
                for req in chunk:
                    dim = req.get("deleteDimensionRequest") or {}
                    start = dim.get("startIndex")
                    if isinstance(start, int):
                        failed.append(start)
        return failed


def _split_sheet_range(range_a1: str) -> tuple[str, str]:
    raw = str(range_a1 or "").strip()
    if "!" in raw:
        sheet_id, rng = raw.split("!", 1)
        return sheet_id.strip(), rng.strip()
    raise ValueError(f"范围须含工作表 ID，例如 xz3aq0!A4:E10，收到 {range_a1!r}")

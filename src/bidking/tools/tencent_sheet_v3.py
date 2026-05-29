"""腾讯文档在线表格 Open API V3 客户端（读范围 / batchUpdate 写、删行）。"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from bidking.config.paths import project_root
from bidking.logsys.app_log import log_timestamp

_A1_RANGE_RE = re.compile(
    r"^([A-Za-z]+)(\d+)(?::([A-Za-z]+)(\d+))?$",
)
_BATCH_REQUEST_LIMIT = 5
_MAX_RANGE_ROWS = 1000
_MAX_RANGE_COLS = 200
_MAX_RANGE_CELLS = 10000
_DEFAULT_REQUEST_LOG_REL = Path("logs") / "tencent_sheet_v3.log"
_REQUEST_LOG_ENV = "BIDKING_TENCENT_SHEET_V3_LOG_PATH"
_REQUEST_LOG_LOCK = threading.Lock()


def resolve_tencent_sheet_v3_log_path(
    openapi: dict[str, Any] | None = None,
) -> Path | None:
    """
    解析 V3 请求日志路径。

    - ``openapi.request_log: false`` 关闭
    - ``openapi.request_log_path`` 或环境变量 ``BIDKING_TENCENT_SHEET_V3_LOG_PATH``
    - 默认 ``<项目根>/logs/tencent_sheet_v3.log``
    """
    branch = openapi if isinstance(openapi, dict) else {}
    if branch.get("request_log") is False:
        return None
    raw = str(
        branch.get("request_log_path")
        or os.environ.get(_REQUEST_LOG_ENV)
        or ""
    ).strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_absolute():
            return p.resolve()
        return (project_root() / p).resolve()
    return (project_root() / _DEFAULT_REQUEST_LOG_REL).resolve()


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    out = dict(headers)
    token = out.get("Access-Token", "")
    if token:
        shown = str(token)[:6]
        out["Access-Token"] = f"{shown}…({len(token)} chars)" if len(token) > 6 else "***"
    return out


def _summarize_grid_data(grid: Any) -> dict[str, Any]:
    if not isinstance(grid, dict):
        return {}
    rows = grid.get("rows")
    n = len(rows) if isinstance(rows, list) else 0
    return {
        "startRow": grid.get("startRow"),
        "startColumn": grid.get("startColumn"),
        "rowCount": n,
    }


def _summarize_batch_request_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"raw": repr(item)[:120]}
    if "updateRangeRequest" in item:
        req = item["updateRangeRequest"]
        gd = req.get("gridData") if isinstance(req, dict) else None
        sheet_id = req.get("sheetId") if isinstance(req, dict) else None
        summary = _summarize_grid_data(gd)
        summary["sheetId"] = sheet_id
        return {"updateRangeRequest": summary}
    if "deleteDimensionRequest" in item:
        req = item["deleteDimensionRequest"]
        if isinstance(req, dict):
            return {
                "deleteDimensionRequest": {
                    "sheetId": req.get("sheetId"),
                    "dimension": req.get("dimension"),
                    "startIndex": req.get("startIndex"),
                    "endIndex": req.get("endIndex"),
                }
            }
    keys = list(item.keys())[:4]
    return {"keys": keys}


def summarize_for_request_log(obj: Any, *, depth: int = 0) -> Any:
    """压缩请求/响应体，避免日志过大或泄露单元格全文。"""
    if depth > 8:
        return "..."
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        if len(obj) > 240:
            return obj[:240] + f"…({len(obj)} chars)"
        return obj
    if isinstance(obj, list):
        if len(obj) > 20:
            head = [summarize_for_request_log(x, depth=depth + 1) for x in obj[:20]]
            return head + [f"…+{len(obj) - 20} items"]
        return [summarize_for_request_log(x, depth=depth + 1) for x in obj]
    if isinstance(obj, dict):
        if "gridData" in obj:
            return {"gridData": _summarize_grid_data(obj.get("gridData"))}
        if "requests" in obj and isinstance(obj["requests"], list):
            reqs = obj["requests"]
            return {
                "requests": [
                    _summarize_batch_request_item(r) for r in reqs[:10]
                ]
                + ([f"…+{len(reqs) - 10} requests"] if len(reqs) > 10 else [])
            }
        out: dict[str, Any] = {}
        for key, val in obj.items():
            if key in ("data", "gridData") and isinstance(val, dict):
                if "gridData" in val:
                    out[key] = {"gridData": _summarize_grid_data(val.get("gridData"))}
                else:
                    out[key] = summarize_for_request_log(val, depth=depth + 1)
            else:
                out[key] = summarize_for_request_log(val, depth=depth + 1)
        return out
    return repr(obj)[:120]


def _append_request_log_line(path: Path, line: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _REQUEST_LOG_LOCK:
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line + "\n")
    except OSError as exc:
        import sys

        print(
            f"写入 V3 请求日志失败 ({path}): {exc}",
            file=sys.stderr,
        )


def log_http_exchange(
    log_path: Path | None,
    *,
    tag: str,
    method: str,
    url: str,
    headers: dict[str, str],
    status: str,
    elapsed_ms: float,
    body: dict[str, Any] | None = None,
    response: Any = None,
    error: str | None = None,
) -> None:
    """写入腾讯相关 HTTP 请求日志（表格 V3 / Bot 门禁文档等共用）。"""
    if log_path is None:
        return
    parts = [
        f"[{log_timestamp()}] [{tag}] {method.upper()} {url}",
        f"  status={status} elapsed_ms={elapsed_ms:.1f}",
        f"  headers={json.dumps(_redact_headers(headers), ensure_ascii=False)}",
    ]
    if body is not None:
        parts.append(
            "  request="
            + json.dumps(summarize_for_request_log(body), ensure_ascii=False)
        )
    if response is not None:
        parts.append(
            "  response="
            + json.dumps(summarize_for_request_log(response), ensure_ascii=False)
        )
    if error:
        parts.append(f"  error={error}")
    _append_request_log_line(log_path, "\n".join(parts))


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


def normalize_a1_range_for_api(range_a1: str) -> str:
    """
    转为腾讯文档 V3 GET 接受的 A1 区域。

    单格 ``C6`` 须写成 ``C6:C6``，否则 ``Range Validate error``。
    """
    raw = str(range_a1 or "").strip()
    if "!" in raw:
        sheet, _, rest = raw.partition("!")
        rest = rest.strip()
        normalized = normalize_a1_range_for_api(rest)
        return f"{sheet}!{normalized}"
    if ":" in raw:
        return raw
    m = _A1_RANGE_RE.match(raw)
    if not m:
        raise ValueError(f"无效 A1 区域: {range_a1!r}")
    c1, r1, c2, r2 = m.group(1), m.group(2), m.group(3), m.group(4)
    if c2 is None:
        return f"{c1}{r1}:{c1}{r1}"
    return raw


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


def range_cell_count(range_a1: str) -> int:
    """A1 区域总单元格数（用于校验 Open API 范围限制）。"""
    row_start, col_start, row_end, col_end = parse_a1_range(range_a1)
    rows = row_end - row_start + 1
    cols = col_end - col_start + 1
    return rows * cols


def max_rows_per_update_chunk(*, ncol: int) -> int:
    """单次 ``updateRangeRequest`` 允许的最大行数。"""
    ncol = max(1, int(ncol))
    if ncol > _MAX_RANGE_COLS:
        raise ValueError(
            f"列数 {ncol} 超过 Open API 单次上限 {_MAX_RANGE_COLS}"
        )
    return min(_MAX_RANGE_ROWS, _MAX_RANGE_CELLS // ncol)


def iter_value_row_chunks(
    values: list[list[str | dict[str, Any]]],
) -> list[tuple[int, list[list[str | dict[str, Any]]]]]:
    """
    将写入数据按 Open API 行数/单元格上限切块。

    返回 ``(chunk 起始行偏移, 行数据)`` 列表，偏移相对 ``values`` 首行。
    """
    if not values:
        return []
    ncol = max(len(row) for row in values)
    chunk_rows = max_rows_per_update_chunk(ncol=ncol)
    out: list[tuple[int, list[list[str]]]] = []
    for offset in range(0, len(values), chunk_rows):
        out.append((offset, values[offset : offset + chunk_rows]))
    return out


def iter_a1_row_subranges(
    range_a1: str,
    *,
    max_rows: int | None = None,
) -> list[str]:
    """将 A1 行区域按行数上限拆成多个子区域（列不变）。"""
    row_start, col_start, row_end, col_end = parse_a1_range(range_a1)
    left = _col_index_to_letter(col_start)
    right = _col_index_to_letter(col_end)
    total_rows = row_end - row_start + 1
    ncol = col_end - col_start + 1
    limit = max_rows if max_rows is not None else max_rows_per_update_chunk(ncol=ncol)
    if total_rows <= limit and ncol <= _MAX_RANGE_COLS:
        cells = total_rows * ncol
        if cells <= _MAX_RANGE_CELLS:
            return [range_a1]
    step = max(1, limit)
    ranges: list[str] = []
    for start in range(row_start, row_end + 1, step):
        end = min(start + step - 1, row_end)
        ranges.append(f"{left}{start}:{right}{end}")
    return ranges


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


def build_sheet_cell(
    value: str | int | float,
    *,
    as_number: bool = False,
    font_size: int | None = None,
) -> dict[str, Any]:
    """构造 V3 单元格（``cellValue`` + 可选 ``cellFormat.textFormat.fontSize``）。"""
    cell: dict[str, Any] = {}
    if as_number:
        if isinstance(value, (int, float)):
            number = int(value) if float(value).is_integer() else float(value)
        else:
            raw = str(value or "").strip().replace(",", "")
            number = int(float(raw or 0))
        cell["cellValue"] = {"number": number}
    else:
        cell["cellValue"] = {"text": str(value)}
    if font_size is not None:
        cell["cellFormat"] = {"textFormat": {"fontSize": int(font_size)}}
    return cell


def _coerce_grid_cell(cell: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(cell, dict) and "cellValue" in cell:
        return cell
    return build_sheet_cell(str(cell))


def build_update_range_request(
    *,
    sheet_id: str,
    start_row_1based: int,
    start_col_1based: int,
    values: list[list[str | dict[str, Any]]],
) -> dict[str, Any]:
    """构造 ``updateRangeRequest``（行列均为 1-based 入参，内部转 0-based）。"""
    rows_payload: list[dict[str, Any]] = []
    for line in values:
        rows_payload.append(
            {"values": [_coerce_grid_cell(v) for v in line]}
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
        request_log_path: Path | str | None = None,
        request_log: bool | None = None,
        openapi_config: dict[str, Any] | None = None,
    ) -> None:
        self.file_id = file_id.strip()
        self.client_id = client_id.strip()
        self.open_id = open_id.strip()
        self.access_token = access_token.strip()
        self.timeout = timeout
        if request_log is False:
            self._request_log_path: Path | None = None
        elif request_log_path is not None:
            p = Path(request_log_path).expanduser()
            self._request_log_path = (
                p.resolve()
                if p.is_absolute()
                else (project_root() / p).resolve()
            )
        else:
            self._request_log_path = resolve_tencent_sheet_v3_log_path(
                openapi_config if isinstance(openapi_config, dict) else None
            )
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

    def _log_http_exchange(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any] | None,
        status: str,
        response: Any,
        elapsed_ms: float,
        error: str | None = None,
    ) -> None:
        log_http_exchange(
            self._request_log_path,
            tag="tencent-sheet-v3",
            method=method,
            url=url,
            headers=headers,
            body=body,
            status=status,
            response=response,
            elapsed_ms=elapsed_ms,
            error=error,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"https://docs.qq.com{path}"
        headers = self._headers()
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers=headers, method=method.upper()
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self._log_http_exchange(
                method=method,
                url=url,
                headers=headers,
                body=body,
                status=f"HTTP {exc.code}",
                response=detail[:2000] if detail else None,
                elapsed_ms=elapsed_ms,
                error=detail[:500] if detail else str(exc),
            )
            raise RuntimeError(f"Open API V3 HTTP {exc.code}: {detail}") from exc
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._log_http_exchange(
                method=method,
                url=url,
                headers=headers,
                body=body,
                status="invalid_json",
                response=raw[:2000],
                elapsed_ms=elapsed_ms,
                error=str(exc),
            )
            raise RuntimeError(f"Open API V3 响应非 JSON: {raw[:200]}") from exc
        if not isinstance(payload, dict):
            self._log_http_exchange(
                method=method,
                url=url,
                headers=headers,
                body=body,
                status="bad_payload",
                response=payload,
                elapsed_ms=elapsed_ms,
                error="响应格式异常",
            )
            raise RuntimeError(f"Open API V3 响应格式异常: {payload!r}")
        ret = payload.get("ret", payload.get("code"))
        if ret not in (0, None, "0"):
            self._log_http_exchange(
                method=method,
                url=url,
                headers=headers,
                body=body,
                status=f"ret={ret}",
                response=payload,
                elapsed_ms=elapsed_ms,
                error=str(payload.get("msg") or payload.get("message") or ""),
            )
            raise RuntimeError(
                f"Open API V3 业务失败 ret={ret} msg="
                f"{payload.get('msg') or payload.get('message')!r}"
            )
        self._log_http_exchange(
            method=method,
            url=url,
            headers=headers,
            body=body,
            status="ok",
            response=payload,
            elapsed_ms=elapsed_ms,
        )
        return payload

    def _get_range_grid_once(
        self,
        sheet_id: str,
        range_a1: str,
    ) -> tuple[int, int, list[list[str]]]:
        rng = normalize_a1_range_for_api(range_a1)
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

    def get_range_grid(
        self,
        sheet_id: str,
        range_a1: str,
    ) -> tuple[int, int, list[list[str]]]:
        """读取区域，返回 ``(起始行 1-based, 起始列 1-based, 行数据)``。"""
        subranges = iter_a1_row_subranges(range_a1)
        if len(subranges) == 1:
            return self._get_range_grid_once(sheet_id, subranges[0])
        first_row = 0
        first_col = 0
        merged: list[list[str]] = []
        for sub in subranges:
            row_start, col_start, rows = self._get_range_grid_once(sheet_id, sub)
            if not merged:
                first_row, first_col = row_start, col_start
            merged.extend(rows)
        return first_row, first_col, merged

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
        values: list[list[str | dict[str, Any]]],
    ) -> None:
        """写入矩形区域（超限时自动拆成多个 updateRangeRequest）。"""
        if not values:
            return
        row_start, col_start, _, _ = parse_a1_range(range_a1)
        requests: list[dict[str, Any]] = []
        for offset, chunk in iter_value_row_chunks(values):
            requests.append(
                build_update_range_request(
                    sheet_id=sheet_id,
                    start_row_1based=row_start + offset,
                    start_col_1based=col_start,
                    values=chunk,
                )
            )
        self.batch_update(requests)

    def read_count_at_row(
        self,
        *,
        sheet_id: str,
        row_index: int,
        count_col: str,
        fallback: int = 0,
        parse_count: Any = None,
    ) -> int:
        col = str(count_col or "C").strip().upper() or "C"
        range_a1 = f"{col}{row_index}:{col}{row_index}"
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
        for row_index in sorted(row_indices, reverse=True):
            try:
                self.batch_update(
                    [
                        build_delete_rows_request(
                            sheet_id=sheet_id, row_index_1based=row_index
                        )
                    ]
                )
            except RuntimeError:
                failed.append(row_index)
        return failed

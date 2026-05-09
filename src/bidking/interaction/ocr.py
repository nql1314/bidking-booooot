"""RapidOCR 单例（共用 onnx 引擎，避免重复初始化）。

历史上 ``fresh_bidking_bot.rapidocr_once`` 等平台各处各自维护 RapidOCR 实例。
本模块统一为单一单例；OCR 入口由 ``_legacy_bot.rapidocr_once`` 等使用。
"""

from __future__ import annotations

import threading
from typing import Any, List, Tuple

_LOCK = threading.Lock()
_ENGINE: Any = None


def _normalize_rapid_output(raw: Any) -> List[Any]:
    """统一 onnxruntime 旧接口与新 ``rapidocr`` 的 ``RapidOCROutput``。

    目标格式（与 ``rapidocr_onnxruntime`` 一致）：``[(box, text, score), ...]``，
    ``box`` 为可多边形点坐标序列（可被现有排序逻辑用 ``point[0]`` / ``point[1]`` 读取）。
    """
    if raw is None:
        return []
    # rapidocr-onnxruntime: ``(result, elapsed)``
    if isinstance(raw, tuple) and len(raw) >= 1:
        first = raw[0]
        if first is None:
            return []
        if isinstance(first, list):
            return first
        raw = first
    # 已是列表（兜底）
    if isinstance(raw, list):
        return raw
    # rapidocr >=2.x: RapidOCROutput(txts=..., boxes=..., scores=...)
    txts = getattr(raw, "txts", None)
    boxes = getattr(raw, "boxes", None)
    scores = getattr(raw, "scores", None)
    if txts is None or len(txts) == 0:
        return []
    if boxes is None:
        dummy = [[0, 0], [1, 0], [1, 1], [0, 1]]
        score_tuple_empty = scores if scores is not None else ()
        return [
            (
                dummy,
                str(txts[i]),
                float(score_tuple_empty[i]) if i < len(score_tuple_empty) else 1.0,
            )
            for i in range(len(txts))
        ]

    def _box_at(idx: int) -> Any:
        if hasattr(boxes, "__len__") and idx < len(boxes):
            box = boxes[idx]
            return box.tolist() if hasattr(box, "tolist") else box
        return [[0, 0], [0, 0], [0, 0], [0, 0]]

    score_tuple = scores if scores is not None else ()
    n = len(txts)
    out: List[Any] = []
    for i in range(n):
        sc = float(score_tuple[i]) if i < len(score_tuple) else 1.0
        out.append((_box_at(i), str(txts[i]), sc))
    return out


def _build_engine() -> Any:
    """优先 ``rapidocr_onnxruntime``（Python <3.13），否则回退到新包 ``rapidocr``。"""
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except ImportError:
        from rapidocr import RapidOCR  # type: ignore
    return RapidOCR()


def get_engine() -> Any:
    global _ENGINE
    if _ENGINE is None:
        with _LOCK:
            if _ENGINE is None:
                _ENGINE = _build_engine()
    return _ENGINE


def infer_lines(image: Any) -> List[Any]:
    """对图像跑一次 OCR，返回统一行列表 ``[(box, text, score), ...]``。"""
    raw = get_engine()(image)
    return _normalize_rapid_output(raw)


def rapidocr_once(image: Any) -> List[Tuple[Any, str, float]]:
    """对单张图像跑 RapidOCR，返回 ``[(box, text, score), ...]``。"""
    return infer_lines(image)  # type: ignore[return-value]


def reset_engine() -> None:
    """主要供测试用。"""
    global _ENGINE
    with _LOCK:
        _ENGINE = None


__all__ = ["get_engine", "infer_lines", "rapidocr_once", "reset_engine"]

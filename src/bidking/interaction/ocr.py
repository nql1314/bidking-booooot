"""RapidOCR 单例（共用 onnx 引擎，避免重复初始化）。

本模块为单一单例；OCR 入口由 ``_legacy_bot.rapidocr_once`` 等使用。
仅支持 PyPI 包 ``rapidocr``（Python 3.13+）。
"""

from __future__ import annotations

import threading
from typing import Any, List, Tuple

import numpy as np

_LOCK = threading.Lock()
_ENGINE: Any = None


def _coerce_image_for_rapidocr(image: Any) -> Any:
    """``rapidocr`` 接受 str / ndarray / bytes / Path；调用方传 PIL 时转为 RGB ndarray。"""
    try:
        from PIL import Image as PILImage
    except ImportError:
        return image
    if not isinstance(image, PILImage.Image):
        return image
    if image.mode != "RGB":
        image = image.convert("RGB")
    return np.ascontiguousarray(np.asarray(image, dtype=np.uint8))


def _normalize_rapid_output(raw: Any) -> List[Any]:
    """将 ``RapidOCROutput`` 规范为 ``[(box, text, score), ...]``（box 为多边形点序列）。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
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
    raw = get_engine()(_coerce_image_for_rapidocr(image))
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

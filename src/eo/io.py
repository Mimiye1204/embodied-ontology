# -*- coding: utf-8 -*-
"""本体数据文件的统一加载：.json = 原始实体清单；.jsonld = JSON-LD 文档（自动 round-trip）。"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from .jsonld import from_jsonld_document


def load_entities_file(path: str) -> List[Dict[str, Any]]:
    """从文件加载本体实体清单。

    - .json / 其它：按原始实体清单读取（[{id, type, ...}, ...]）
    - .jsonld / .json-ld：按 JSON-LD 文档读取（@context + @graph），经 from_jsonld_document 重建实体
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    lowered = path.lower()
    if lowered.endswith(".jsonld") or lowered.endswith(".json-ld"):
        if not isinstance(data, dict) or "@graph" not in data:
            raise ValueError(f"{path} 不是合法的 JSON-LD 文档（缺 @graph）")
        return from_jsonld_document(data)

    if not isinstance(data, list):
        raise ValueError(f"{path} 应是实体清单列表（[{{...}}, ...]）")
    return data

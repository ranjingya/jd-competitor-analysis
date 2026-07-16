"""读取并解析商品主图素材。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import SCRIPTS_DIR


LOGGER = logging.getLogger(__name__)
PRODUCT_IMAGES_PATH = SCRIPTS_DIR.parent / "assets" / "product-images.json"


def load_product_images(path: Path = PRODUCT_IMAGES_PATH) -> dict[str, dict[str, str | None]]:
    """读取商品主图素材字典。

    功能说明：读取并校验按商品 ID 索引的主图素材，返回供报告生成阶段查询的稳定字典。
    参数 path：商品主图素材 JSON 路径，默认读取 Skill 根目录下的正式素材文件。
    返回值：键为商品 ID、值包含维护名称和 HTTPS 主图地址的字典。
    """

    LOGGER.info("开始读取商品主图素材：%s", path)
    if not path.is_file():
        LOGGER.warning("商品主图素材文件不存在，报告将使用缺图占位：%s", path)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        raise ValueError("商品主图素材 schema_version 必须为 1.0")
    raw_products = data.get("products")
    if not isinstance(raw_products, dict):
        raise ValueError("商品主图素材 products 必须是对象")

    products: dict[str, dict[str, str | None]] = {}
    for raw_id, raw_item in raw_products.items():
        product_id = str(raw_id).strip()
        if not product_id or not isinstance(raw_item, dict):
            raise ValueError(f"商品主图素材条目无效：{raw_id}")
        name = raw_item.get("name")
        image_url = raw_item.get("image_url")
        if name is not None and not isinstance(name, str):
            raise ValueError(f"商品主图素材 name 必须是字符串或 null：{product_id}")
        if image_url is not None:
            if not isinstance(image_url, str):
                raise ValueError(f"商品主图素材 image_url 必须使用 HTTPS：{product_id}")
            image_url = image_url.strip()
            parsed_url = urlparse(image_url)
            if parsed_url.scheme != "https" or not parsed_url.netloc:
                raise ValueError(f"商品主图素材 image_url 必须使用 HTTPS：{product_id}")
        products[product_id] = {
            "name": name.strip() if isinstance(name, str) and name.strip() else None,
            "image_url": image_url,
        }
        LOGGER.info("商品主图素材已加载：id=%s，has_image=%s", product_id, bool(image_url))
    LOGGER.info("商品主图素材读取完成：count=%s", len(products))
    return products


def resolve_product_reference(
    product_id: str | None,
    product_name: str | None,
    product_images: dict[str, dict[str, Any]],
) -> dict[str, str | None]:
    """生成报告使用的商品引用。

    功能说明：按商品 ID 查询主图素材，并优先使用分析结果中的真实商品名称组装前端展示字段。
    参数 product_id：分析对象的商品 ID。
    参数 product_name：原始分析数据提供的商品名称。
    参数 product_images：已校验的商品主图素材字典。
    返回值：包含商品 ID、名称和可空主图地址的报告字段。
    """

    normalized_id = str(product_id).strip() if product_id is not None else None
    asset = product_images.get(normalized_id or "", {})
    if normalized_id and not asset:
        LOGGER.warning("商品主图素材缺失：id=%s", normalized_id)
    resolved_name = product_name or asset.get("name")
    return {
        "id": normalized_id,
        "name": resolved_name,
        "image_url": asset.get("image_url"),
    }

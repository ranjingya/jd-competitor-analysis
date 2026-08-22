"""同步外部商品主图配置到已有报告。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jd_competitor_analysis.product_assets import load_product_images

from ..config import get_settings
from ..database import Database
from ..repositories.report_repository import ReportRepository


def sync_product_images(
    database: Database,
    product_images_path: Path,
) -> dict[str, Any]:
    """读取商品主图文件并同步已有报告。

    功能说明：初始化统一数据库，读取并校验运行数据目录中的商品主图配置，
    再按 SPU 更新所有已有报告的主图字段。
    参数 database：统一 Backend 数据库。
    参数 product_images_path：外部商品主图 JSON 文件路径。
    返回值：包含数据库路径、配置路径和更新数量的同步摘要。
    """

    database.initialize()
    product_images = load_product_images(product_images_path)
    result = ReportRepository(database).sync_product_images(product_images)
    return {
        "database_path": str(database.path),
        "product_images_path": str(product_images_path),
        **result,
    }


def run_product_image_sync(args: Any) -> None:
    """执行商品主图手动同步命令。

    功能说明：根据统一运行配置定位数据库和商品主图文件，完成同步并输出 JSON 摘要。
    参数 args：命令行参数命名空间；当前命令只使用统一运行配置。
    返回值：无；同步摘要写入标准输出。
    """

    settings = get_settings()
    result = sync_product_images(Database(settings.database_path), settings.product_images_path)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

"""测试商品主图配置读取与地址校验。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jd_competitor_analysis.product_assets import is_valid_product_image_url, load_product_images


class ProductAssetsTest(unittest.TestCase):
    """验证商品主图支持 HTTPS 与同源静态图片。"""

    def test_supported_product_image_urls(self) -> None:
        """HTTPS 地址和商品主图公共路径应通过校验。"""

        self.assertTrue(is_valid_product_image_url("https://example.com/product.jpg"))
        self.assertTrue(is_valid_product_image_url("/product-images/10001.png"))
        self.assertFalse(is_valid_product_image_url("http://example.com/product.jpg"))
        self.assertFalse(is_valid_product_image_url("/product-images/../secret.txt"))

    def test_local_product_image_is_loaded(self) -> None:
        """配置文件中的同源商品主图路径应保留原值。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "product-images.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "products": {
                            "10001": {
                                "name": "测试商品",
                                "image_url": "/product-images/10001.png",
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            products = load_product_images(config_path)

        self.assertEqual(products["10001"]["image_url"], "/product-images/10001.png")


if __name__ == "__main__":
    unittest.main()

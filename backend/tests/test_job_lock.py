"""测试日分析进程锁。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.job_lock import acquire_job_lock


class JobLockTest(unittest.TestCase):
    """验证同一路径只能由一个分析流程持有。"""

    def test_second_lock_is_rejected_until_release(self) -> None:
        """第一个上下文释放前第二次获取应失败，释放后可以再次获取。"""

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "daily.lock"
            with acquire_job_lock(path) as first:
                with acquire_job_lock(path) as second:
                    self.assertTrue(first)
                    self.assertFalse(second)
            with acquire_job_lock(path) as third:
                self.assertTrue(third)


if __name__ == "__main__":
    unittest.main()

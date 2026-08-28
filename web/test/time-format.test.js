import assert from "node:assert/strict";
import test from "node:test";

import { formatBeijingDateTime } from "../src/time-format.js";


test("UTC 时间按北京时间展示", () => {
  assert.equal(
    formatBeijingDateTime("2026-08-27T07:27:11+00:00"),
    "2026-08-27 15:27:11"
  );
});

test("北京时间保持相同墙上时间", () => {
  assert.equal(
    formatBeijingDateTime("2026-08-27T15:27:11+08:00"),
    "2026-08-27 15:27:11"
  );
});

test("无效时间返回空字符串", () => {
  assert.equal(formatBeijingDateTime("not-a-time"), "");
  assert.equal(formatBeijingDateTime(null), "");
});

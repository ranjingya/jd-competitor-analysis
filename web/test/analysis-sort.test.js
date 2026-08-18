import assert from "node:assert/strict";
import test from "node:test";

import {
  compareTableValues,
  isBottomSortValue,
  sortFlatTreeRowsBySiblings,
  sortRowsWithBottomValues
} from "../src/analysis-sort.js";

test("短横线、空值、null 与零值属于沉底值", () => {
  ["-", "", null, undefined, 0, "0", "0.00"].forEach((value) => {
    assert.equal(isBottomSortValue(value), true);
  });
  [12, -3, "8.50", "本品领先"].forEach((value) => {
    assert.equal(isBottomSortValue(value), false);
  });
});

test("升降序都把沉底值放在有效数值之后", () => {
  const values = [0, 12, "-", 3, null, -2];
  assert.deepEqual([...values].sort((a, b) => compareTableValues(a, b, "asc")), [
    -2, 3, 12, 0, "-", null
  ]);
  assert.deepEqual([...values].sort((a, b) => compareTableValues(a, b, "desc")), [
    12, 3, -2, 0, "-", null
  ]);
});

test("树形排序仅比较同一层级并递归处理子节点", () => {
  const rows = [
    {
      id: "parent-zero",
      value: 0,
      _X_ROW_CHILD: [
        { id: "child-zero", value: 0 },
        { id: "child-high", value: 20 },
        { id: "child-low", value: 5 }
      ]
    },
    { id: "parent-high", value: 30, _X_ROW_CHILD: [] },
    { id: "parent-low", value: 10, _X_ROW_CHILD: [] }
  ];

  const sorted = sortRowsWithBottomValues(rows, [{ field: "value", order: "desc" }]);
  assert.deepEqual(sorted.map((row) => row.id), ["parent-high", "parent-low", "parent-zero"]);
  assert.deepEqual(sorted[2]._X_ROW_CHILD.map((row) => row.id), [
    "child-high", "child-low", "child-zero"
  ]);
});

test("扁平父子数据按兄弟节点排序并保持父节点在子节点之前", () => {
  const rows = [
    { id: "root", parent_id: null, value: 100 },
    { id: "search", parent_id: "root", value: 52.5 },
    { id: "recommend", parent_id: "root", value: 17.5 },
    { id: "recommend-core", parent_id: "recommend", value: 17.5 },
    { id: "recommend-other", parent_id: "recommend", value: 0.5 },
    { id: "game", parent_id: "root", value: 0.5 },
    { id: "missing", parent_id: "root", value: null }
  ];

  const descending = sortFlatTreeRowsBySiblings(rows, [{ field: "value", order: "desc" }]);
  assert.deepEqual(descending.map((row) => row.id), [
    "root",
    "search",
    "recommend",
    "recommend-core",
    "recommend-other",
    "game",
    "missing"
  ]);

  const ascending = sortFlatTreeRowsBySiblings(rows, [{ field: "value", order: "asc" }]);
  assert.deepEqual(ascending.map((row) => row.id), [
    "root",
    "game",
    "recommend",
    "recommend-other",
    "recommend-core",
    "search",
    "missing"
  ]);
});

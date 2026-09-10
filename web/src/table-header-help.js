import { h, ref, nextTick, Teleport, onBeforeUnmount } from "vue";

let sequence = 0;

/** 根据列定义 column 返回计算说明；没有说明的列返回 null。 */
export function headerHelpText(column) {
  const key = column.suffix || column.key;
  if (/(^|_)current_level_visitor_rate_pct$/.test(key)) return "当前渠道访客估值 ÷ 同一父级下直接子渠道的有效访客估值合计。";
  if (/(^|_)total_visitor_rate_pct$/.test(key)) return "当前渠道访客估值 ÷ 一级渠道的有效访客估值合计。不使用顶部 SKU 访客合计。";
  if (/(^|_)visitors$/.test(key)) return "渠道访客数取数仓区间中位值；缺失数据不当作零。";
  return null;
}

export const TableHeaderHelp = {
  props: ["text", "label"],
  /** 创建表头提示交互；props.text 为说明内容，props.label 为指标名；返回组件渲染函数。 */
  setup(props) {
    // 提示挂载到页面顶层，避免表头裁切，并限制在视口内。
    const id = `analysis-header-help-${++sequence}`;
    const tip = ref(null);
    const visible = ref(false);
    const position = ref({});
    let timer;
    const close = () => { clearTimeout(timer); visible.value = false; };
    const show = async (target) => {
      clearTimeout(timer);
      visible.value = true;
      await nextTick();
      if (!tip.value || !target.isConnected) return close();
      const box = target.getBoundingClientRect();
      const size = tip.value.getBoundingClientRect();
      position.value = {
        left: `${Math.max(8, Math.min(box.x + box.width / 2 - size.width / 2, window.innerWidth - size.width - 8))}px`,
        top: `${Math.max(8, Math.min(box.top >= size.height + 16 ? box.top - size.height - 8 : box.bottom + 8, window.innerHeight - size.height - 8))}px`
      };
    };
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    onBeforeUnmount(() => {
      close();
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    });
    return () => h("span", { class: "analysis-header-help-wrap" }, [
      h("button", {
        type: "button", class: "analysis-header-help", "aria-label": `${props.label}计算说明`,
        "aria-describedby": visible.value ? id : undefined,
        onMouseenter: (event) => { const target = event.currentTarget; timer = setTimeout(() => show(target), 350); },
        onMouseleave: close, onFocus: (event) => show(event.currentTarget), onBlur: close,
        onClick: (event) => { event.stopPropagation(); show(event.currentTarget); },
        onKeydown: (event) => { event.stopPropagation(); if (event.key === "Escape") close(); }
      }, [h("svg", { viewBox: "0 0 24 24", width: 14, height: 14, fill: "none", stroke: "currentColor", "stroke-width": 1.7, "aria-hidden": "true" }, [
        h("circle", { cx: 12, cy: 12, r: 9 }),
        h("path", { d: "M9.5 9a2.5 2.5 0 0 1 5 0c0 1.7-2.5 2-2.5 4", "stroke-linecap": "round" }),
        h("circle", { cx: 12, cy: 16.5, r: .8, fill: "currentColor", stroke: "none" })
      ])]),
      visible.value ? h(Teleport, { to: "body" }, h("div", { id, ref: tip, role: "tooltip", class: "analysis-header-tooltip", style: position.value }, props.text)) : null
    ]);
  }
};

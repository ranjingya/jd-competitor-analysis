import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const webRoot = fileURLToPath(new URL(".", import.meta.url));

/**
 * 功能说明：把 ECharts 与其渲染依赖拆成独立缓存包。
 * 参数 moduleId：Rollup 当前处理的模块路径。
 * 返回值：ECharts 依赖返回固定分包名，其他模块交给默认策略。
 */
function splitVendorChunk(moduleId) {
  if (moduleId.includes("/node_modules/echarts/") || moduleId.includes("/node_modules/zrender/")) {
    return "echarts";
  }
  return undefined;
}

export default defineConfig({
  root: webRoot,
  define: {
    __VUE_OPTIONS_API__: true,
    __VUE_PROD_DEVTOOLS__: false,
    __VUE_PROD_HYDRATION_MISMATCH_DETAILS__: false
  },
  build: {
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      input: {
        main: resolve(webRoot, "index.html")
      },
      output: {
        manualChunks: splitVendorChunk
      }
    }
  },
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:8000"
    }
  },
  preview: {
    port: 4173,
    strictPort: false,
    proxy: {
      "/api": "http://127.0.0.1:8000"
    }
  }
});

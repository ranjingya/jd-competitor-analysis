import { createReadStream, existsSync, statSync } from "node:fs";
import { resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const webRoot = fileURLToPath(new URL(".", import.meta.url));
const outputRoot = resolve(process.env.REPORT_OUTPUT_DIR || resolve(webRoot, "../output"));
const emptyIndex = JSON.stringify({
  schema_version: "1.0",
  updated_at: null,
  meta: {},
  reports: { day: [], week: [], month: [] }
});

/**
 * 功能说明：把 Skill 内的 `scripts/output` 以只读方式映射到 `/reports/`。
 * 参数 server：Vite 开发或预览服务器实例。
 * 返回值：无；中间件直接处理报告文件请求。
 */
function installReportMiddleware(server) {
  server.middlewares.use((request, response, next) => {
    if (!request.url || !["GET", "HEAD"].includes(request.method || "")) {
      next();
      return;
    }
    const pathname = decodeURIComponent(new URL(request.url, "http://127.0.0.1").pathname);
    if (!pathname.startsWith("/reports/")) {
      next();
      return;
    }
    const relativePath = pathname.slice("/reports/".length);
    const isReportFile = relativePath === "report-index.json" || relativePath.endsWith("/analysis_result.json");
    if (!isReportFile) {
      response.statusCode = 404;
      response.end("Not Found");
      return;
    }
    const targetPath = resolve(outputRoot, relativePath);
    const allowedPrefix = `${outputRoot}${sep}`;
    if (targetPath !== outputRoot && !targetPath.startsWith(allowedPrefix)) {
      response.statusCode = 403;
      response.end("Forbidden");
      return;
    }
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", "application/json; charset=utf-8");
    if (!existsSync(targetPath) || !statSync(targetPath).isFile()) {
      if (relativePath === "report-index.json") {
        response.statusCode = 200;
        response.end(emptyIndex);
        return;
      }
      response.statusCode = 404;
      response.end(JSON.stringify({ error: "报告不存在" }));
      return;
    }
    response.statusCode = 200;
    if (request.method === "HEAD") {
      response.end();
      return;
    }
    createReadStream(targetPath).pipe(response);
  });
}

function reportFilesPlugin() {
  return {
    name: "report-files",
    configureServer: installReportMiddleware,
    configurePreviewServer: installReportMiddleware
  };
}

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
  plugins: [reportFilesPlugin()],
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
    strictPort: true
  },
  preview: {
    port: 4173,
    strictPort: false
  }
});

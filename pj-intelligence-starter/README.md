# PJ Intelligence V0.1

PJ Intelligence 当前定位为 Google To C Product OS。
News / Items 是辅助观察层。
Market Signals 是市场信号层。
后续主线是：
Search Demand → Market Signal → Keyword Cluster → Competitor Page → Opportunity Card → Page Factory → GEO / AEO Audit → Validation Review。

本地仍抓取公开资讯，去重后写入 SQLite，按本地规则排序，在页面上查看。模型只在手动点击时调用。

## 启动

```bash
cp .env.example .env
docker compose up --build -d
```

## 打开

http://localhost:8765

## 健康检查

```bash
curl http://localhost:8765/api/health
```

## 采集

页面点击「立即采集」，或：

```bash
curl -X POST http://localhost:8765/api/collect
```

## 接入模型

编辑 `.env`，填写 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL_FAST`。

`LLM_BASE_URL` 可以填 `https://example.com` 或 `https://example.com/v1`，程序都会请求 `https://example.com/v1/chat/completions`。

## 注意

- `.env` 不要提交
- 默认不自动消耗模型额度
- 只有点击「AI 研判」才调用模型

# 相似文章判定接口文档

## 1. 概述

- **服务目标**：为实时入库的新闻/稿件计算 80% 以上文本重合的相似关系，并输出所属文章组合（cluster）。
- **处理模式**：`指纹预筛 -> 精确验证 -> 动态聚类`。接口层只暴露异步化的任务提交与查询，计算由后台 worker 完成。
- **版本**：`v1`（所有路径前缀 `/api/v1`）。
- **认证**：建议使用 HTTP Header `X-API-Key` 或者 `Authorization: Bearer <token>`，本文默认已完成鉴权。
- **数据格式**：`application/json; charset=utf-8`；时间统一为 ISO8601（UTC）。

---

## 2. 错误返回约定

```json
{
  "error": {
    "code": "ARTICLE_NOT_FOUND",
    "message": "article_id=202411090001 not found"
  },
  "trace_id": "b72e1d5fe0c94d27a6a3f2168ea20d83"
}
```

| 字段 | 描述 |
|------|------|
| `error.code` | 机器可解析的错误码，详见附录 |
| `error.message` | 人类可读描述 |
| `trace_id` | 可用于日志关联的链路 ID |

HTTP 状态码与 `error.code` 对齐，如参数错误返回 `400 BAD_REQUEST`。

---

## 3. 数据模型

### 3.1 Article（文章）

```json
{
  "article_id": "202411090001",
  "title": "A 股三大指数集体收涨",
  "content": "<全文字符串，<=200k 字符>",
  "publish_time": "2024-11-09T08:31:15Z",
  "source": "news_link",
  "cluster_id": "cluster_5f843c29",
  "cluster_status": "matched",
  "similarity_score": 0.87,
  "created_at": "2024-11-09T08:31:17Z",
  "updated_at": "2024-11-09T08:31:18Z"
}
```

| 字段 | 说明 |
|------|------|
| `cluster_status` | `pending`（等待后台精确比对）、`matched`（已找到相似组）、`unique`（确认无相似） |
| `similarity_score` | 新文章与当前簇代表的最大 Jaccard 值（0-1），`unique` 时为空 |

### 3.2 Cluster（组合）

```json
{
  "cluster_id": "cluster_5f843c29",
  "article_ids": [
    "202411081120",
    "202411090001",
    "202411090243"
  ],
  "size": 3,
  "representative_article_id": "202411081120",
  "last_updated": "2024-11-09T08:31:18Z",
  "top_terms": [
    {"term": "A股", "weight": 0.31},
    {"term": "涨幅", "weight": 0.27}
  ]
}
```

`top_terms` 可由 ES 的倒排统计或缓存生成，用于前端展示。

---

## 4. 接口列表

| Method | Path | 描述 |
|--------|------|------|
| `POST` | `/api/v1/articles` | 入库文章并触发相似度判断 |
| `GET` | `/api/v1/articles/{article_id}` | 查询单篇文章及其 cluster 状态 |
| `GET` | `/api/v1/articles/{article_id}/similar` | 获取文章所属组合及成员 |
| `GET` | `/api/v1/clusters/{cluster_id}` | 查询组合详情 |
| `GET` | `/api/v1/clusters` | 分页列出组合，支持过滤 |
| `POST` | `/api/v1/articles/recheck` | 触发指定文章重新比对（人工复核入口） |
| `GET` | `/api/v1/system/health` | 系统健康检查（ES、队列、worker） |

下文详细说明核心接口。

---

## 5. API 详情

### 5.1 `POST /api/v1/articles`

**用途**：接收新增文章，返回初步 cluster 状态。内部会写 ES 并投递到 `similarity_jobs` 队列，精确验证在后台完成。

**请求体**

```json
{
  "article_id": "202411090001",
  "title": "A 股三大指数集体收涨",
  "content": "……",
  "publish_time": "2024-11-09T08:31:15Z",
  "source": "news_link",
  "language": "zh-CN",
  "metadata": {
    "channel": "finance",
    "url": "https://news.example.com/1"
  }
}
```

**响应示例**

```json
{
  "article_id": "202411090001",
  "cluster_status": "pending",
  "cluster_id": null,
  "candidate_cluster_id": "cluster_5f843c29",
  "finalize_eta_ms": 120,
  "trace_id": "b72e1d5fe0c94d27a6a3f2168ea20d83"
}
```

| 字段 | 描述 |
|------|------|
| `candidate_cluster_id` | 通过 MinHash 召回的最优组合（可用于前端占位） |
| `finalize_eta_ms` | 预估剩余处理时间，便于前端轮询 |

**幂等性**：`article_id` 作为幂等键，再次提交同 ID 返回已有记录。

---

### 5.2 `GET /api/v1/articles/{article_id}`

**用途**：查询文章完整状态，包括 cluster 信息。

**响应示例**

```json
{
  "article": {
    "article_id": "202411090001",
    "title": "A 股三大指数集体收涨",
    "publish_time": "2024-11-09T08:31:15Z",
    "source": "news_link",
    "cluster_status": "matched",
    "cluster_id": "cluster_5f843c29",
    "similarity_score": 0.87
  },
  "cluster": {
    "cluster_id": "cluster_5f843c29",
    "size": 3,
    "representative_article_id": "202411081120",
    "last_updated": "2024-11-09T08:31:18Z"
  },
  "trace_id": "b72e1d5fe0c94d27a6a3f2168ea20d83"
}
```

---

### 5.3 `GET /api/v1/articles/{article_id}/similar`

**用途**：快速获取文章所属组合及所有成员，供前端展示“相似文章组合”。

**响应示例**

```json
{
  "cluster_id": "cluster_5f843c29",
  "articles": [
    {
      "article_id": "202411081120",
      "title": "A 股三大指数收涨",
      "similarity_score": 0.92
    },
    {
      "article_id": "202411090001",
      "title": "A 股三大指数集体收涨",
      "similarity_score": 0.87
    },
    {
      "article_id": "202411090243",
      "title": "午评：A 股涨势延续",
      "similarity_score": 0.81
    }
  ],
  "trace_id": "22f35dbde87c4cf89f337e0ca46f9d27"
}
```

如果文章仍处于 `pending` 状态，应返回 `404` 并提示“CLUSTER_PENDING”。

---

### 5.4 `GET /api/v1/clusters/{cluster_id}`

**用途**：查询组合详情及代表性特征。

**可选查询参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `include_articles` | `bool` | 是否携带全部文章列表，默认 `false` |

**响应示例**

```json
{
  "cluster": {
    "cluster_id": "cluster_5f843c29",
    "size": 3,
    "article_ids": [
      "202411081120",
      "202411090001",
      "202411090243"
    ],
    "representative_article_id": "202411081120",
    "top_terms": [
      {"term": "A股", "weight": 0.31},
      {"term": "指数", "weight": 0.28}
    ],
    "last_updated": "2024-11-09T08:31:18Z"
  },
  "trace_id": "9a38427ebb054f19aeb8cd1f125f23e3"
}
```

当 `include_articles=true` 时，可额外返回 `articles` 数组（同 5.3）。

---

### 5.5 `GET /api/v1/clusters`

**用途**：分页列出相似组合，便于后台运营/展示。

**查询参数**

| 参数 | 默认 | 说明 |
|------|------|------|
| `page` | 1 | 页码（≥1） |
| `page_size` | 20 | 每页数量，<=100 |
| `min_size` | 2 | 最小组合成员数 |
| `max_age_minutes` | - | 仅返回最近 N 分钟内更新的组合 |
| `sort` | `last_updated:desc` | 支持 `size`、`last_updated` |

**响应示例**

```json
{
  "clusters": [
    {"cluster_id": "cluster_5f843c29", "size": 3, "last_updated": "2024-11-09T08:31:18Z"},
    {"cluster_id": "cluster_3d8a1c02", "size": 5, "last_updated": "2024-11-09T08:29:02Z"}
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total": 642
  },
  "trace_id": "c8bd6ae6bce8481abef864d4af9f9cf8"
}
```

---

### 5.6 `POST /api/v1/articles/recheck`

**用途**：对指定文章或组合做人工复核，触发重新比对流程（重新计算 MinHash/Shingles 并写入任务队列）。

**请求体**

```json
{
  "article_ids": ["202411090001", "202411081120"],
  "reason": "manual_review"
}
```

**响应**

```json
{
  "accepted": true,
  "job_id": "recheck_20241109_0012",
  "trace_id": "0d75b0bde9254a7ca13334817b8a9a5f"
}
```

---

### 5.7 `GET /api/v1/system/health`

**用途**：供运维/监控探活，检查 ES、消息队列、相似度 worker、Redis 等依赖。

```json
{
  "status": "pass",
  "components": {
    "elasticsearch": "pass",
    "kafka": "pass",
    "worker": "pass",
    "redis": "pass"
  },
  "timestamp": "2024-11-09T08:31:19Z"
}
```

`status` 可取 `pass` / `warn` / `fail`，配合 HTTP 200/503。

---

## 6. 典型调用流程

1. **入库**：调用 `POST /articles` 提交文章，立即得到 `cluster_status=pending`。
2. **轮询**：前端按 `finalize_eta_ms` 间隔轮询 `GET /articles/{id}`。
3. **展示组合**：一旦状态为 `matched`，调用 `GET /articles/{id}/similar` 渲染组合。
4. **后台审核**：运营通过 `GET /clusters` 浏览组合，必要时 `POST /articles/recheck` 触发复核。

如需更低延迟，可配置回调 Webhook（拓展接口，本文略）。

---

## 7. 错误码附录

| 错误码 | HTTP | 描述 | 解决建议 |
|--------|------|------|----------|
| `INVALID_ARGUMENT` | 400 | 参数缺失或格式错误 | 检查请求体 |
| `ARTICLE_ALREADY_EXISTS` | 409 | `article_id` 已存在 | 使用新的 `article_id` 或忽略 |
| `ARTICLE_NOT_FOUND` | 404 | 文章不存在 | 确认 ID 是否正确 |
| `CLUSTER_PENDING` | 404 | 文章尚未完成相似度判定 | 稍后重试 |
| `CLUSTER_NOT_FOUND` | 404 | 组合不存在 | 检查 `cluster_id` |
| `RECHECK_RATE_LIMITED` | 429 | 复核触发过于频繁 | 等待冷却时间 |
| `UPSTREAM_UNAVAILABLE` | 503 | ES/Kafka/Redis 等依赖异常 | 稍后重试或联系运维 |

---

## 8. 版本规划

- `v1`：当前文档，主打 MinHash + Jaccard。
- `v1.1`（规划中）：支持回调 Webhook、按频道/栏目订阅组合事件。
- `v2`（预研）：引入多模态指纹（标题图片 + 文本），支持跨语言相似度。

若接口有重大变动，将在 `/api/v2` 提供并保留 v1 至少 6 个月。


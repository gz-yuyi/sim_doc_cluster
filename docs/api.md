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
  "state": 1,
  "top": 0,
  "tags": [
    {"id": 1001, "name": "A股"},
    {"id": 1002, "name": "收涨"}
  ],
  "topic": [
    {"id": "topic_macro", "name": "宏观经济"}
  ],
  "cluster_id": "cluster_5f843c29",
  "cluster_status": "matched",
  "similarity_score": 0.87,
  "created_at": "2024-11-09T08:31:17Z",
  "updated_at": "2024-11-09T08:31:18Z"
}
```

| 字段 | 说明 |
|------|------|
| `state` | 文章可见状态：`0` 不可见、`1` 可见、`2` 删除 |
| `top` | 是否置顶：`0` 否、`1` 是 |
| `tags` | 标签列表，元素包含 `id:number` + `name:string`，用于后续召回和前端展示 |
| `topic` | 主题列表，元素包含 `id:string` + `name:string`，用于专题聚合 |
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
| `GET` | `/api/v1/clusters` | 文章搜索接口（返回符合条件的文章 ID 列表） |
| `POST` | `/api/v1/articles/recheck` | 触发指定文章重新比对（人工复核入口） |
| `GET` | `/api/v1/system/health` | 系统健康检查（ES、队列、worker） |

下文详细说明核心接口。

---

## 5. API 详情

### 5.1 `POST /api/v1/articles`

**用途**：同步文章本体信息（含业务状态、标签、主题），触发后台相似度计算任务。接口幂等，`article_id` 已存在时更新可变字段（如状态、标签）。

**请求体**

```json
{
  "article_id": "202411090001",
  "title": "A 股三大指数集体收涨",
  "content": "<全文字符串，<=200k 字符>",
  "publish_time": "2024-11-09T08:31:15Z",
  "source": "news_link",
  "state": 1,
  "top": 0,
  "tags": [
    {"id": 1001, "name": "A股"},
    {"id": 1002, "name": "收涨"}
  ],
  "topic": [
    {"id": "topic_macro", "name": "宏观经济"}
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `article_id` | string | 全局唯一 ID，作为幂等键，必填 |
| `title` | string | 文章标题，必填 |
| `content` | string | 文章正文，最大 200000 字符，必填 |
| `publish_time` | string(date-time) | 发布时间（ISO8601），必填 |
| `source` | string | 来源平台或渠道，必填 |
| `state` | integer | 文章状态：`0` 不可见、`1` 可见、`2` 删除，必填 |
| `top` | integer | 置顶标记：`0` 否、`1` 是，必填 |
| `tags` | array<object> | 必填，标签列表，元素包含 `id:number`（标签 ID）与 `name:string`（标签名称），可传空数组 |
| `topic` | array<object> | 必填，主题列表，元素包含 `id:string` 与 `name:string`，可传空数组 |

> `tags` 与 `topic` 同时用于业务展示和相似度的召回限制，如果无可用值请传空数组，避免缺省字段影响 schema 校验。

**响应示例**

```json
{}
```

接口成功返回 `200 OK` 和空对象，表示同步任务已写入。文章初始 cluster 状态可以随后通过 `GET /api/v1/articles/{article_id}` 查询。若需要 `candidate_cluster_id` 等实时信息，可在查询接口中获取。

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

**用途**：文章搜索接口。根据文章状态、置顶、标题、来源、时间区间、标签、主题等条件搜索，并返回满足条件的文章 ID 列表。用于前端或运营系统先拿到文章集合，再通过 `GET /api/v1/articles/{id}` 批量获取详情。

**查询参数（均为可选）**

| 参数 | 类型 | 说明 |
|------|------|------|
| `page` | integer | 页码，默认 `1` |
| `page_size` | integer | 每页数量，默认 `20`，建议 ≤100 |
| `sort` | string | 排序字段与方向，如 `publish_time:desc` |
| `state` | integer | 文章状态：`0` 不可见、`1` 可见、`2` 删除 |
| `top` | integer | 是否置顶：`0` 否、`1` 是 |
| `title` | string | 标题模糊搜索关键词 |
| `source` | integer | 来源平台 ID |
| `start_time` | string | 发布时间范围起点，ISO8601 |
| `end_time` | string | 发布时间范围终点，ISO8601 |
| `tag_id` | string | 一级标签 ID |
| `topic` | array<string> | 主题 ID 列表，支持多选（重复 query 参数或 JSON 数组均可） |

**响应示例**

```json
[
    {
        "article_id": "202411081120",
        "similar_article_ids": [
          "202411081120",
          "202411090001"
        ]
    }
]
```

| 字段 | 说明 |
|------|------|
| `article_id` | 符合搜索条件的文章主 ID。若需要分页信息，可在响应头补充或扩展字段；当前版本仅返回 ID 数组。 |
| `similar_article_ids` | 同组文章 ID 数组，第一项为 `article_id` 本身，其余为同一簇中其他文章（若存在）。 |

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

1. **入库**：调用 `POST /articles` 提交文章，立即得到 `200 OK`。
2. **轮询**：前端按业务配置的时间间隔（建议 1~3s）轮询 `GET /articles/{id}`。
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

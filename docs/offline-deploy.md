# 离线部署指引

使用 `scripts/export-offline-bundle.sh` 可以拉取镜像并导出离线包，离线包包含：

- Docker 镜像归档（`images/sim-doc-cluster-images.tar`）
- `docker-compose.yml`
- `.env.example`
- 本说明文档

## 生成离线包

```bash
./scripts/export-offline-bundle.sh /tmp/sim-doc-offline
```

- 需要已经登录对应镜像仓库，并保证 Docker、Docker Compose 可用。
- 输出目录会自动创建；已有同名文件会被覆盖。

## 使用离线包部署

1. 将输出目录拷贝到离线环境，例如 `/opt/sim-doc-offline`。
2. 导入镜像：
   ```bash
   docker load -i /opt/sim-doc-offline/images/sim-doc-cluster-images.tar
   ```
3. 按需复制并修改环境变量：
   ```bash
   cd /opt/sim-doc-offline
   cp .env.example .env
   # 编辑 .env 填写 ES/Redis 账号等
   ```
4. 启动：
   ```bash
   docker compose up -d
   ```

若需要调整 worker 数量、内存等，直接编辑 `docker-compose.yml` 后再执行 `docker compose up -d` 使其生效。

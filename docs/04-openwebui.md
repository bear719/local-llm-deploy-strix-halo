# Open WebUI 部署与使用手册

日期：2026-10-07
主机：AMD Ryzen AI MAX+ 395（Strix Halo）
状态：**已上线运行**

---

## 访问地址

| 用途 | 地址 |
|---|---|
| 本机访问 | <http://127.0.0.1:3000> |
| 局域网访问 | <http://<主机局域网IP>:3000> |

首次打开需注册账号，**注册的第一个账号自动成为管理员**。

---

## 已接入的服务

| 服务 | 容器内地址 | 说明 |
|---|---|---|
| llama.cpp（GPU，主力） | `http://host.docker.internal:8080/v1` | Qwen3.6-35B-A3B / Qwen3.8-27B |
| FLM（NPU，8219） | `http://host.docker.internal:8219/v1` | Qwen3.5-4B-NPU2 等 |
| SearXNG 联网搜索 | `http://host.docker.internal:8888/search` | 已有容器，已预配 |

API Key 统一填 `sk-no-key`（llama.cpp 与 FLM 均不校验）。

---

## 接入 8219（NPU）端点 —— 需手动补一步

8080 端点已通过环境变量 `OPENAI_API_BASE_URL` 自动接入。
**8219 端点需在 UI 内手动添加**（Open WebUI 的 `OPENAI_API_BASE_URLS` 仅支持单值环境变量）：

1. 右上角头像 → **设置** → **连接**
2. 「OpenAI API」区域点 **+** 新增一条连接
   - URL：`http://host.docker.internal:8219/v1`
   - 密钥：`sk-no-key`
3. 保存后，模型下拉框即可切换 FLM 的 NPU 模型

> 若要两个端点都用环境变量方式，可改用 `OPENAI_API_BASE_URLS`（复数，分号分隔）：
> `http://host.docker.internal:8080/v1;http://host.docker.internal:8219/v1`

---

## 关键踩坑记录

### ★ HF 下载阻塞导致启动失败（本次核心问题）

**症状**：容器 `Up (unhealthy)`，宿主 3000 端口已 LISTEN 但 `curl` 返回 `000`（无响应）。

**日志特征**：
```
[Errno 101] Network is unreachable
thrown while requesting HEAD https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/...
Retrying in 8s [Retry 5/5]
```

**根因**：Open WebUI 首次启动必须下载 RAG 嵌入模型 `all-MiniLM-L6-v2`。
容器内 `huggingface.co` 不可达，5 次重试全失败 → 应用启动流程阻塞 → uvicorn 不监听端口。

**正解**：加环境变量 `-e HF_ENDPOINT=https://hf-mirror.com`

**验证**：容器内 `curl https://hf-mirror.com` 返回 `200`，容器内不通原站但通镜像站。

**注意区分**：日志里 HF 出现 `404 Not Found`（如 `chat_template.jinja`）是**正常现象**，
说明镜像站可达、只是该文件不存在，不影响启动。真正致命的是 `Network is unreachable`。

### Docker 权限

当前用户不在 `docker` 组，所有 docker 命令需 sudo。
凭据文件：`~/.workbuddy/.docker-sudo`（chmod 600）。
用法：`cat ~/.workbuddy/.docker-sudo | sudo -S -k docker <cmd>`

### shell 重定向坑

`-e SEARCH_SEARXNG_ENGINE_QUERY_URL=...?q=<query>` 中的 `<query>` 会被 bash 当输入重定向
→ 报 `query: 没有那个文件或目录`。**必须给整个键值对加引号**。

---

## 常用运维命令

```bash
# 查看状态
cat ~/.workbuddy/.docker-sudo | sudo -S -k docker ps --filter name=open-webui

# 看日志
cat ~/.workbuddy/.docker-sudo | sudo -S -k docker logs -f open-webui

# 重启 / 停止
cat ~/.workbuddy/.docker-sudo | sudo -S -k docker restart open-webui
cat ~/.workbuddy/.docker-sudo | sudo -S -k docker stop open-webui

# 健康检查
curl -s http://127.0.0.1:3000/health

# 一键重建（保留数据）
bash $HOME/WorkBuddy/调试本地模型/start-openwebui.sh
```

---

## 回滚方案

```bash
# 完全移除（不影响 8080 / 8219 / 8888 服务）
cat ~/.workbuddy/.docker-sudo | sudo -S -k docker rm -f open-webui
rm -rf $HOME/WorkBuddy/调试本地模型/openwebui-data
```

---

## 配置速查

| 项 | 值 |
|---|---|
| 镜像 | `ghcr.io/open-webui/open-webui:main`（v0.11.4） |
| 端口映射 | `3000:8080` |
| 数据目录 | `$HOME/WorkBuddy/调试本地模型/openwebui-data` |
| 容器名 | `open-webui` |
| 重启策略 | `always` |
| WEBUI_SECRET_KEY | `change-me` |
| 资源占用 | 镜像约 1.5 GB；运行时 RSS 约 500 MB–1 GB |

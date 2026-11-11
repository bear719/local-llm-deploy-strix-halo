#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 tools/docproxy.py 打入「NPU 旁路分流」补丁（12 处精确替换）。

设计原则
--------
1. 默认关闭：NPU_UPSTREAM 为空时，所有代码路径与打补丁前完全一致。
2. 显式分流：只认 X-Backend: npu 头 / model 白名单 / 可选 sidecar 端点，
   绝不根据 prompt 内容猜测，避免把重要请求误送到 4B NPU。
3. 不静默回落：NPU 故障时由既有 forward_to_upstream 返回 502；
   host RAM 低于水位线时返回 503，均不偷偷改走 8080。
4. 保留既有全部修复：chunked 上传解码、SSE select 心跳、
   STREAM_READ_TIMEOUT=600、非 2xx 原样回传、孤儿 media marker 剥离、
   X-Trim-Prompt、enable_thinking 注入，逻辑一概不动。
5. 可回滚：--apply 前自动备份；--revert 从备份原样恢复。

用法
----
  python3 tools/apply-npu-route.py --check      # 只校验 12 处 old_string 是否唯一匹配
  python3 tools/apply-npu-route.py --dry-run    # 打印 unified diff，不写文件
  python3 tools/apply-npu-route.py --apply      # 备份 + 写入
  python3 tools/apply-npu-route.py --revert     # 从备份恢复

生效方式（在 docproxy 实例的环境里加一个变量，重启即生效）：
  NPU_UPSTREAM=http://127.0.0.1:8219
逻辑回滚只需去掉该变量，无需改代码。
"""

import argparse
import difflib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "docproxy.py")
BACKUP = os.path.join(HERE, "docproxy.py.bak.20261108-npu")

# ---------------------------------------------------------------------------
# 新增区块 A：NPU 配置常量，插在 PREVIEW_LIMITS 之后
# ---------------------------------------------------------------------------
CONST_BLOCK = '''# ---------- NPU 旁路分流（2026-11-08 新增，默认关闭 → 天然可回滚） ----------
# 只接受「显式标记」的分流，绝不根据 prompt 内容猜测，避免把重要请求误送 4B。
# NPU_UPSTREAM 留空时，所有代码路径与打补丁前完全一致；清空该变量即完成逻辑回滚。
NPU_UPSTREAM = os.environ.get("NPU_UPSTREAM", "").rstrip("/")
NPU_MODEL_TAG = os.environ.get("NPU_MODEL_TAG", "lfm2.5-it:1.2b")
NPU_MODEL_ALIASES = set(
    x.strip().lower()
    for x in os.environ.get(
        "NPU_MODEL_ALIASES",
        # 2026-11-08：默认旁路模型改为 lfm2.5-it:1.2b（v1.0.12 已装）；
        # 4B 旧权重在 v1.0.3+ 已失效，仅保留别名以兼容既有客户端。
        "lfm2.5-it:1.2b,qwen3.5:4b,qwen3.5:2b,qwen3.5:0.8b,"
        "embed-gemma:300m,whisper-v3:turbo",
    ).split(",") if x.strip()
)
# 置 1 才让 /v1/embeddings 与 /v1/audio/* 自动分流（需 flm 以 --embed/--asr 启动）
NPU_SIDECAR = os.environ.get("NPU_SIDECAR", "0").lower() not in ("0", "false", "no")
# host RAM 水位线（MiB）。NPU 进程吃的是 30.47 GiB host RAM，不是 96 GiB carve-out；
# 2026-10-08 实测 HIP 分配 20 GiB 时 avail 仅 494 MiB → 全局 OOM，故必须设闸门。
NPU_MIN_MEMAVAIL_MIB = int(os.environ.get("NPU_MIN_MEMAVAIL_MIB", "4096"))'''

# ---------------------------------------------------------------------------
# 新增区块 B：路由函数，插在 forward_to_upstream 定义之前
# ---------------------------------------------------------------------------
FUNC_BLOCK = '''class NpuRouteError(Exception):
    """分流被拒（水位线不足等），由 do_POST 转成显式 503，不静默回落到 8080。"""


def mem_available_mib():
    """读取 /proc/meminfo 的 MemAvailable（MiB），读不到返回 None。"""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        return None
    return None


def npu_route(headers, body, path):
    """返回 (base_url, is_npu)。base_url=None 表示继续走默认 8080 上游。"""
    if not NPU_UPSTREAM:
        return None, False
    force = (headers.get("X-Backend") or "").strip().lower() == "npu"
    model = (body.get("model") or "") if isinstance(body, dict) else ""
    alias_hit = str(model).strip().lower() in NPU_MODEL_ALIASES
    sidecar_hit = NPU_SIDECAR and (
        path.startswith("/v1/embeddings") or path.startswith("/v1/audio/")
    )
    if not (force or alias_hit or sidecar_hit):
        return None, False
    if NPU_MIN_MEMAVAIL_MIB > 0:
        avail = mem_available_mib()
        if avail is not None and avail < NPU_MIN_MEMAVAIL_MIB:
            raise NpuRouteError(
                "MemAvailable %s MiB < %s MiB，NPU 分流暂停（不回落到 8080）"
                % (avail, NPU_MIN_MEMAVAIL_MIB)
            )
    return NPU_UPSTREAM, True


'''

# ---------------------------------------------------------------------------
# 12 处精确替换：(名称, 原文, 新文)
# 每一处 old 都必须在当前 docproxy.py 中恰好出现 1 次，否则整体中止。
# ---------------------------------------------------------------------------
REPLACEMENTS = [
    (
        "① 常量区插入 NPU 配置",
        '''PREVIEW_LIMITS = {".md": 2000, ".txt": 2000, ".log": 2000, ".csv": 1500,
                  ".pdf": 500, ".docx": 500, ".pptx": 500, ".xlsx": 800}''',
        '''PREVIEW_LIMITS = {".md": 2000, ".txt": 2000, ".log": 2000, ".csv": 1500,
                  ".pdf": 500, ".docx": 500, ".pptx": 500, ".xlsx": 800}

''' + CONST_BLOCK,
    ),
    (
        "② 插入路由函数 + forward_to_upstream 增加 base_url/content_type 参数",
        "def forward_to_upstream(self, method, path, raw=None, stream=False):",
        FUNC_BLOCK
        + "def forward_to_upstream(self, method, path, raw=None, stream=False,\n"
          "                        base_url=None, content_type=None):",
    ),
    (
        "③ 上游地址改为可选",
        "    u = urllib.parse.urlparse(UPSTREAM)",
        "    u = urllib.parse.urlparse(base_url or UPSTREAM)",
    ),
    (
        "④ Content-Type 支持原样透传（ASR multipart 需要 boundary）",
        '''        conn.request(method, path, body=body,
                     headers={"Content-Type": "application/json"})''',
        '''        conn.request(method, path, body=body,
                     headers={"Content-Type": content_type or "application/json"})''',
    ),
    (
        "⑤ body 解析加固：multipart 二进制会抛 UnicodeDecodeError，旧代码未捕获",
        '''        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {}''',
        '''        try:
            body = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            # ASR 的 multipart/form-data 含二进制音频，不是 JSON，不能当请求体解析
            body = {}''',
    ),
    (
        "⑥ do_POST 解析完路径后判定分流",
        '''        p = self.path.split("?")[0].rstrip("/")

        # ★ 2026-10-03 修复：剥离孤儿 media 占位符，避免 mmproj tokenizer 400''',
        '''        p = self.path.split("?")[0].rstrip("/")

        # ★ 2026-11-08：NPU 旁路分流判定（默认关闭；被拒时显式 503，不回落到 8080）
        try:
            npu_base, is_npu = npu_route(self.headers, body, p)
        except NpuRouteError as e:
            self._send(503, {"error": "npu route rejected: %s" % e})
            return

        # ★ 2026-10-03 修复：剥离孤儿 media 占位符，避免 mmproj tokenizer 400''',
    ),
    (
        "⑦ /health 暴露 NPU 开关状态",
        '''        if p in ("", "/health"):
            self._send(200, {"status": "ok", "proxy": "docproxy",
                             "mode": PROXY_MODE, "upstream": UPSTREAM})''',
        '''        if p in ("", "/health"):
            self._send(200, {"status": "ok", "proxy": "docproxy",
                             "mode": PROXY_MODE, "upstream": UPSTREAM,
                             "npu_upstream": NPU_UPSTREAM or None,
                             "npu_enabled": bool(NPU_UPSTREAM)})''',
    ),
    (
        "⑧ /v1/models 支持按 X-Backend 查 NPU 侧模型",
        '''        elif p in ("/v1/models", "/models"):
            forward_to_upstream(self,"GET", "/v1/models")''',
        '''        elif p in ("/v1/models", "/models"):
            want_npu = (self.headers.get("X-Backend") or "").strip().lower() == "npu"
            forward_to_upstream(
                self, "GET", "/v1/models",
                base_url=NPU_UPSTREAM if (want_npu and NPU_UPSTREAM) else None)''',
    ),
    (
        "⑨ NPU 请求跳过 llama.cpp 特有的 enable_thinking 注入",
        "            if INJECT_NO_THINK and isinstance(body, dict) and raw:",
        "            if INJECT_NO_THINK and not is_npu and isinstance(body, dict) and raw:",
    ),
    (
        "⑩ NPU 请求强制 passthrough，跳过 disclosure 工具循环",
        '            if PROXY_MODE == "disclosure" and not body.get("stream"):',
        '            if PROXY_MODE == "disclosure" and not is_npu and not body.get("stream"):',
    ),
    (
        "⑪ chat 分支：改写 model 字段 + 指定 NPU 上游",
        '''            else:
                # passthrough 模式，或 disclosure 下的流式请求 → 原样透传（含 SSE）
                forward_to_upstream(self,"POST", "/v1/chat/completions", raw,
                                        stream=bool(body.get("stream")))''',
        '''            else:
                # passthrough 模式，或 disclosure 下的流式请求 → 原样透传（含 SSE）
                if is_npu and isinstance(body, dict):
                    # flm 按 model 字段定位/热切换模型；主模型别名会触发一次昂贵换模
                    # 或直接报「找不到模型」，故统一改写成 NPU 侧标签。
                    if str(body.get("model") or "").lower() not in NPU_MODEL_ALIASES:
                        body["model"] = NPU_MODEL_TAG
                        raw = json.dumps(body).encode()
                forward_to_upstream(self,"POST", "/v1/chat/completions", raw,
                                        stream=bool(body.get("stream")),
                                        base_url=npu_base)''',
    ),
    (
        "⑫ 通用 /v1/ 分支：支持 NPU 上游与 multipart Content-Type",
        '''        elif p.startswith("/v1/") or p in ("/embeddings", "/completions"):
            forward_to_upstream(self,"POST", self.path.split("?")[0], raw)''',
        '''        elif p.startswith("/v1/") or p in ("/embeddings", "/completions"):
            ctype = None
            if is_npu:
                # ASR 是 multipart/form-data，必须把含 boundary 的原 Content-Type 带给 flm
                ctype = self.headers.get("Content-Type") or "application/json"
            forward_to_upstream(self,"POST", self.path.split("?")[0], raw,
                                base_url=npu_base, content_type=ctype)''',
    ),
]


def build_new(src):
    """按顺序应用 12 处替换；任一 old 不唯一即抛错，保证不写出半截文件。"""
    for name, old, new in REPLACEMENTS:
        cnt = src.count(old)
        if cnt != 1:
            raise SystemExit(
                "[ERROR] %s：期望恰好 1 处匹配，实际 %d 处 -> 拒绝继续\n"
                "        可能 docproxy.py 已被改动或已打过补丁，请先 --check。"
                % (name, cnt)
            )
        src = src.replace(old, new, 1)
    return src


def main():
    ap = argparse.ArgumentParser(description="docproxy NPU 分流补丁")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="只校验匹配，不写文件")
    g.add_argument("--dry-run", action="store_true", help="打印 unified diff，不写文件")
    g.add_argument("--apply", action="store_true", help="备份并写入")
    g.add_argument("--revert", action="store_true", help="从备份恢复")
    a = ap.parse_args()

    if a.revert:
        if not os.path.exists(BACKUP):
            raise SystemExit("[ERROR] 备份不存在：%s -> 无法回滚" % BACKUP)
        shutil.copy2(BACKUP, TARGET)
        print("[OK] 已从备份恢复 %s" % TARGET)
        print("     备份文件：%s" % BACKUP)
        return 0

    if not os.path.exists(TARGET):
        raise SystemExit("[ERROR] 找不到 %s" % TARGET)
    with open(TARGET, encoding="utf-8") as f:
        src = f.read()

    if a.check:
        for name, old, _ in REPLACEMENTS:
            cnt = src.count(old)
            print("  %-56s 匹配 %d 处 %s" % (name, cnt, "OK" if cnt == 1 else "FAIL"))
        ok = all(src.count(old) == 1 for _, old, _ in REPLACEMENTS)
        print("[%s] 共 %d 处替换点" % ("OK" if ok else "FAIL", len(REPLACEMENTS)))
        return 0 if ok else 1

    new = build_new(src)

    if a.dry_run:
        diff = difflib.unified_diff(
            src.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile="docproxy.py (当前)", tofile="docproxy.py (打补丁后)",
        )
        sys.stdout.writelines(diff)
        print("\n[OK] dry-run 完成，未写文件；共 %d 处替换点全部匹配。" % len(REPLACEMENTS))
        return 0

    if a.apply:
        if not os.path.exists(BACKUP):
            shutil.copy2(TARGET, BACKUP)
            print("[OK] 已备份 -> %s" % BACKUP)
        else:
            print("[提示] 备份已存在，保持不变 -> %s" % BACKUP)
        tmp = TARGET + ".tmp-npu"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, TARGET)
        print("[OK] 补丁已写入 %s" % TARGET)
        print("[提示] 记得重启 docproxy 实例并注入 NPU_UPSTREAM 才会生效；")
        print("       只打补丁不设变量 = 行为与补丁前完全一致。")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# 许可：CC0-1.0，公共领域贡献，无任何限制。

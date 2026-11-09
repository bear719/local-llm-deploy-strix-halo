#!/usr/bin/env python3
"""
预加载 WorkBuddy/Docproxy System Prompt 的 KV cache。

用法：
  # 一次性预热（手动触发）
  python3 tools/preload_system_prompt.py

  # 定时预热（cron 每分钟）
  * * * * * cd /home/<user>/WorkBuddy/调试本地模型 && python3 tools/preload_system_prompt.py >> /tmp/preload.log 2>&1

原理：
  1. 读取当前 catalog 构建 system prompt（含已注册文件目录）
  2. 发送一个静默请求到 llama-server，cache_prompt=true
  3. system prompt 的 KV 会被保存在 slot 的 cache 中
  4. 后续所有相同 system prompt 的请求可直接复用，跳过 2671 token 的 prefill

预期效果：
  - 首次请求 prefill 从 ~3 s → ~0.2 s（跳过 system prompt 部分）
  - 用户消息仍需完整 prefill（约 0.5-2 s，取决于长度）
  - catalog 变化后自动重新预热（下次 cron 触发）

回滚：
  # 停用 cron
  crontab -e  # 注释掉 preload 行

作者：管家 | 2026-11-09
"""

import json
import sys
import time
import urllib.request
import urllib.error

# ---------- 配置 ----------
BASE_URL = "http://127.0.0.1:8080"
SYSTEM_PROMPT = """你在按需提供文档内容的工作模式下工作。
你**没有**文档全文——只有下面的目录（元数据 + 结构轮廓 + 少量开头预览）。
回答涉及文档内容的问题时：
1. 先用 search_file 定位相关行，再用 peek_file 精读该区间；不要盲目 load_file。
2. 一次 peek 不超过 150 行；多个独立检索可以在同一轮并行发起。
3. 目录信息足够回答时（如"文档标题是什么"），直接回答，不调工具。

{catalog}"""

TOOLS_SPEC = [{
    "name": "search_file",
    "description": "在已注册文件中搜索关键词，返回匹配行号和前后 2 行上下文",
    "parameters": {
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "文件 id（从目录获取）"},
            "keyword": {"type": "string", "description": "搜索关键词"}
        },
        "required": ["file_id", "keyword"]
    }
}, {
    "name": "peek_file",
    "description": "精读文件指定区间，返回行内容和上下文",
    "parameters": {
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "文件 id"},
            "line_start": {"type": "integer", "description": "起始行号"},
            "line_end": {"type": "integer", "description": "结束行号"}
        },
        "required": ["file_id", "line_start", "line_end"]
    }
}, {
    "name": "load_file",
    "description": "加载文件到记忆（目录+结构轮廓+开头预览），供后续 search/peek 使用",
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "本地文件路径"}
        },
        "required": ["file_path"]
    }
}, {
    "name": "unload_file",
    "description": "从记忆中卸载文件，释放上下文空间",
    "parameters": {
        "type": "object",
        "properties": {
            "file_id": {"type": "string", "description": "文件 id"}
        },
        "required": ["file_id"]
    }
}]

# ---------- 动态加载 catalog ----------
sys.path.insert(0, '/home/<user>/WorkBuddy/调试本地模型/tools')
sys.path.insert(0, '/home/<user>/WorkBuddy/调试本地模型')


def build_catalog():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("docproxy", "/home/<user>/WorkBuddy/调试本地模型/tools/docproxy.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.build_catalog()
    except Exception as e:
        print(f"[WARN] catalog 加载失败: {e}", file=sys.stderr)
        return ""


def preload():
    """预热 system prompt 的 KV cache。"""
    catalog = build_catalog()
    sys_content = SYSTEM_PROMPT.format(catalog=catalog)

    # 用 /tokenize 获取 token 数（用于日志）
    try:
        r = urllib.request.Request(
            BASE_URL + "/tokenize",
            data=json.dumps({"content": sys_content}).encode(),
            headers={"Content-Type": "application/json"}
        )
        tok_resp = json.loads(urllib.request.urlopen(r, timeout=10).read())
        tok_count = len(tok_resp.get("tokens", []))
    except Exception as e:
        tok_count = "?"
        print(f"[WARN] tokenize 失败: {e}", file=sys.stderr)

    # 发送预热请求
    payload = {
        "messages": [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": "preload_heartbeat"}
        ],
        "max_tokens": 1,
        "temperature": 0,
        "cache_prompt": True
    }

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 预热 system prompt ({tok_count} tokens)", flush=True)

    try:
        r = urllib.request.Request(
            BASE_URL + "/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}
        )
        resp = json.loads(urllib.request.urlopen(r, timeout=30).read())
        timings = resp.get("timings", {})
        cache_n = timings.get("cache_n", 0)
        prompt_n = timings.get("prompt_n", 0)
        prompt_ms = timings.get("prompt_ms", 0) / 1000

        if cache_n > 0:
            print(f"  ✓ cache 命中: {cache_n}/{prompt_n} tokens 复用, prefill {prompt_ms:.2f} s", flush=True)
        else:
            print(f"  ✗ cache 未命中: {prompt_n} tokens 全量 prefill, {prompt_ms:.2f} s", flush=True)
    except Exception as e:
        print(f"  [ERROR] 预热失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    preload()

# 许可：CC0-1.0，公共领域贡献，无任何限制。

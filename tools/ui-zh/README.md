# llama.cpp WebUI 汉化流水线（8080 界面）

## 背景

llama-server 内嵌的 WebUI（SvelteKit 打包产物，`build-vk4/tools/ui/dist/`）**没有 i18n**，
只有英文。汉化方式：把打包产物复制成静态目录 → 按**字符串字面量**替换成中文 →
用 `llama-server --path <目录>` 挂载，覆盖内嵌资源。

- 汉化产物目录：`/home/<user>/llama-ui-zh`（13 MB）
- 启动脚本：`start-qwen36-35b-a3b.sh` 中 `UI_PATH=${UI_PATH-/home/<user>/llama-ui-zh}`

## 关键设计（为什么不是简单全文替换）

朴素做法是 `bundle.js.replace("Settings","设置")`，实测会产生三类事故：

1. **中英混排**：`"Set the API Key if you are using --api-key ..."` 只替换了子串 → 半句话中文。
2. **代码被改坏**：`GET/POST/Bearer/Enter/Tab` 这类既是界面词又是协议/按键名的串被翻译 → 请求与快捷键失效。
3. **偏移错位**：acorn 给的偏移是 **UTF-16 码元**，Python 的字符下标与之不等价（bundle 里有 emoji 等
   代理对），按 Python 下标切片会把 `console.error("No wrapper found")` 切成
   `console.error(""未找到包装器",null` → 语法错误。**必须按 utf-16-le 字节切片。**

因此最终方案是「**只做整串替换 + 文本段替换，绝不子串替换**」：

| 情况 | 处理 |
|---|---|
| 字面量去空白后正好等于词条 | 整串替换（保留首尾空白） |
| 字面量含 HTML 标签或 `${}` 插值 | 按标签/插值切分，**逐段**查段级词表，标签与插值原样保留 |
| 其它 | 不动（宁可留英文，也不产生混排） |

## 脚本清单

| 脚本 | 作用 |
|---|---|
| `extract_strings.py` | 第一轮：从 `tools/ui/src` 抽文案（模板文本节点 / 属性 / TS 字面量），与 bundle 求交集 → `strings_src.json` |
| `extract2.py` / `extract3.py` / `extract4.py` | 补抽小写片段、单词标签、`tooltip:`/`label:` 字段（逐轮修漏） |
| `translate_dict.py` | 调本机 8080 批量翻译 → `dict.json`（整串词表，~800 条） |
| `translate_lits.py` | 模板/HTML 字面量整串翻译 → `dict_lits.json`（旧方案，现仅作参考） |
| `fix_trad.py` | 繁转简兜底（模型偶发繁体） |
| `apply4.py` | **主构建脚本**：重建 `/home/<user>/llama-ui-zh`；同时输出 `segments_todo.json`（未命中文本段） |
| `preview_server.py` | 不重启 8080 的预览器：静态目录 + `/v1` 反代到 8080（端口 8899） |
| `verify_scope.py` | 早期待用的中文位置静态校验（已被 acorn 校验取代） |

`dict.json` 是整串词表，`segments.json` 是段专用词表（两者在 apply4 里合并用于段替换）。

## 重新生成

```bash
cd /home/<user>/WorkBuddy/调试本地模型/tools/ui-zh
/usr/bin/python3 apply4.py          # 产出 /home/<user>/llama-ui-zh
```
若 `segments_todo.json` 里还有**应用自身**的文案（不是第三方库报错），补进
`segments.json` 或 `dict.json` 后重跑 `apply4.py` 即可。

预览（不动 8080）：

```bash
/usr/bin/python3 preview_server.py 8899   # 打开 http://127.0.0.1:8899/
```

## 校验（必做）

```bash
node --check /tmp/zh_final.mjs        # 语法
node /tmp/lits.js <原bundle> <汉化bundle>   # 字面量数量必须一致（128623）
```

## 上线 / 回滚

- 生效：改完目录后重启 llama-server（面板托管，`sudo kill -TERM <pid>` 会 2 s 内被 autoRestart 拉起）。
- 回滚（保留汉化目录）：`UI_PATH= ./start-qwen36-35b-a3b.sh long`，或在面板里给 startCommand 加 `UI_PATH=`。
- 回滚（彻底）：`rm -rf /home/<user>/llama-ui-zh`，脚本会自动跳过 `--path`。

## 已知残留

- 第三方库的运行期报错（pdf.js / mermaid / chevrotain 等）保持英文 —— 它们不出现在正常界面里，
  翻译反而有破坏代码的风险。
- 模型名、量化徽章、token 统计等来自服务端数据，本来就不翻译。
- 浏览器有 Service Worker，**切换后首次访问可能仍显示旧英文界面**：Ctrl+Shift+R 强刷，
  或在开发者工具里注销 Service Worker。

---

许可：CC0-1.0，公共领域贡献，无任何限制。

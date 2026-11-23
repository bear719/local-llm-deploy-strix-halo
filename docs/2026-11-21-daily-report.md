# 运行快照 · 2026-11-21（日报第 63 次）

来源：本机每日自动探测，2026-11-21 05:00 (GMT+8)。

---

## 一、平台实测

| 项 | 值 |
|---|---|
| 8080 | 连续在线第 5 天 |
| decode | **81.24%** 接受率同日测得 **81.6 t/s** 档（落 68–82 区间） |
| 上游 | 上游 release 序列持续推进，本机仍 `b10824`，落后 ≈1766 build |

测速纪律照旧：**任何 decode 数字发布前 `pgrep -c sd-cli` 必须为 0**；prefill 在 GPU 争用下会「显得更快」，单次值不可用。

---

## 二、本期唯一值得记的方法论修正：PR 落地不能用 `merge-base`

历史日报里判断「上游某个 PR 有没有进本机 HEAD」用过：

```bash
git merge-base --is-ancestor 29797 HEAD     # 错误
```

`29797` 是 GitHub 的 PR 编号，**不是 git 对象**，实测直接报：

```
fatal: Not a valid object name 29797
exit 128
```

更糟的是这类命令若包在 `if ...; then` 里，失败分支常被当成「未落地」静默吞掉，长期得出错误结论。

**正确做法**——按 PR 号在其 commit message 里检索：

```bash
git log --oneline --all --grep='29797' -i
git log --oneline HEAD | grep -i 'greedy selection'
```

命中即已落地。重核结果：某「零温度链改 greedy 选择」的采样 PR **确已落地**（HEAD 本身就是那个 commit），此前判「未落地」的几条则确实不在 HEAD 历史中。

> 通用教训：**判断「某改动是否在本机」时，一定要用能在本地真实检索到的东西（commit message / 文件内容 / 二进制符号），不要拿外部系统的 ID 当 git 对象用。**

---

## 三、导播台与视频管线

- 出片参数双漂移（steps 12 + 横屏 800×448）**延续**，社区共识仍是 steps 20–30 + 竖屏 576×1024 + 蒸馏档 cfg 1.0。
- `comfyui_url` 仍指无监听的 8188；`--vae-tiling` 延续；Mesa 6 包 hold @ 26.0.8 延续。
- 同期外部实测补充了 **Flash-Next + MTP Q8_0 头**的数字（某独显平台 +27.9%，接受率 75.59%，build b12315）：说明 MTP 的收益与**draft 头精度**关系很大，Q8_0 头比 Q4 头更稳 —— 本机 35B 的 MTP head 是 Q4_K_M，若出现接受率下滑，可优先试换 Q8 头。

---

## 四、可执行项

与 11-19/11-20 一致（huge pages 环境变量、出片参数复位、`comfyui_url` 清空、`--host` 收窄），本期无新增动作。

---

## 五、风险

- **MTP 输出质量**（#27950 / fork 侧 rejection sampling）已 33+ 日未人工闭环；改 `n-max` 或换 draft 头前后必须做同一 prompt 的输出 diff。
- 上游 build 数以每天 +20~30 的速度膨胀，「落后 build 数」本身没有决策意义 —— **本机是定制 fork，升级只能 cherry-pick，不能整包替换**。

---

*许可：CC0-1.0，公共领域贡献，无任何限制。*

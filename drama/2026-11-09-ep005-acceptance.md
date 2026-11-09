# 开片验收单 · EP005 · 2026-11-09 16:01

- **结论：有风险，可放行**（评分 68 / 100）
- 验收单号：`pf_20261109_155924`
- 分镜指纹：`195caad99e4c8931`（分镜一改即失效）
- 项目：`$HOME/drama-series-agent/projects/凡人修仙传`
- 检查结果：✅ 31 · ⚠️ 6 · ⛔ 0
- 审查模型：`MiniMax-M3.1-Flash`
- 关注点：E5 + stdin 修复后最终复验（经验表补齐 L29/L30）

## 一、本集概览

| 项目 | 值 |
|---|---|
| 镜头数 | `21` |
| 总时长(秒) | `155.98` |
| 关键帧数 | `21` |
| 剧本字数 | `4942` |
| 预估出片时长 | `约 9.5 小时（569 分钟）` |
| 角色 | `墨大夫, 韩立` |

## 二、逐项检查

| 项 | 结果 | 说明 | 证据 |
|---|---|---|---|
| 分镜 jsonl | ✅ | 21 镜（期望 21） | `$HOME/drama-series-agent/templates/凡人修仙传/run/EP005.episode-run.jsonl` |
| 剧本文件 | ✅ | 4942 字，含场景与对白标记 | `$HOME/drama-series-agent/templates/凡人修仙传/剧集/EP005/screenplay.md` |
| 镜头时长 | ✅ | 合计 155.98s，21 镜 | `duration_seconds 求和` |
| 关键帧 | ✅ | 21 张齐备（15.8MB） | `assets/keyframes/*.png` |
| 角色参考图 | ✅ | 2 个角色均有已验收参考图（来源：分镜 ref_characters） | `$HOME/drama-series-agent/data/cast/凡人修仙传` |
| 参考图张数 | ✅ | 21 镜均 ≤ 4 张（最多 SHOT-004=3） | `首帧关键帧 + 角色锚图` |
| 声线参考 | ✅ | 2 个声线齐备 | `$HOME/drama-series-agent/data/cast/凡人修仙传/voices` |
| 视频提示词 | ✅ | 21 镜结构完整，平均 1371 字 | `video_prompt` |
| 渲染参数 | ✅ | 工作流 video_minimax_h3_r2v_fast.json，steps=12，并发=1 | `config.json → render` |
| S1 门禁 | ⚠️ | 文学/角色已验收，音频 missing（原生音轨模式下可接受） | `series_runtime.json → s1_gate.audio_status` |
| 响度一致性 | ✅ | 21 镜逐镜 RMS 极差 2.30 dB（最低 SHOT-008 -28.7 dBFS，最高 SHOT-011 -26.4 dBFS） | `$HOME/drama-series-agent/templates/凡人修仙传/output/EP005/shots` |
| 磁盘余量 | ✅ | 可用 237.1GB，本集预估需 4.5GB | `$HOME/drama-series-agent` |
| 推理服务 | ✅ | llama-server:8080、docproxy:18090 正常 | `/health 探活` |
| 历史基线 | ✅ | 历史 266 条镜头状态，失败 8 条（3.0%），完成间隔中位数 1034.8s | `run/*.status.jsonl` |
| 画外音占比 | ⚠️ | 19/21 镜画外音（90.5%）；3 镜双人同框配 VO：SHOT-004, SHOT-013, SHOT-019；接近配图有声书（EP005 为 90.5%），属剧本创作决策但开片前需确认，且字幕标签口径要同步（--vo-label） | `$HOME/drama-series-agent/templates/凡人修仙传/run/EP005.episode-run.jsonl → voice_offscreen (L24)` |
| 长镜原生音频 | ⚠️ | 4 镜 >10s 且带台词走 H3 原生音频（SHOT-001=15.1s, SHOT-004=15.0s, SHOT-014=15.1s, SHOT-017=15.0s）；实证提示词修不了长时长续写/复读，开片前须先定音频路线（短句拼接或字幕承载），别等 21 镜 ASR 才返工 | `$HOME/drama-series-agent/templates/凡人修仙传/run/EP005.episode-run.jsonl → duration_seconds/audio_mode/dialogue (L17,L18)` |
| 台词三件套 | ⚠️ | 2/6 个 >8s 长台词镜缺收尾/节奏约束：SHOT-009缺起说≤0.5s/念完立刻安静；SHOT-019缺起说≤0.5s/念完立刻安静 | `$HOME/drama-series-agent/templates/凡人修仙传/run/EP005.episode-run.jsonl → video_prompt / duration_seconds (L17)` |
| 提示词互斥冲突 | ✅ | 扫描 42 处提示词，未发现脸/交接互斥词对 | `$HOME/drama-series-agent/templates/凡人修仙传/run/EP005.episode-run.jsonl + $HOME/drama-series-agent/templates/凡人修仙传/assets/keyframes/EP005.manifest.jsonl (L23)` |
| 锁脸参考图 | ✅ | 纯手部/无脸镜均未挂参考图（或本集无此类镜） | `$HOME/drama-series-agent/templates/凡人修仙传/assets/keyframes/EP005.manifest.jsonl → image_prompt / kf_* (L25)` |
| 渲染路线与音色锚 | ⚠️ | 5 镜无画面角色但需音色锚（SHOT-002, SHOT-005, SHOT-012, SHOT-015, SHOT-018）；runner._resolve_render_route 判据 4 要求「单段有画面角色 → A 路」，这类镜可能落 B 路 I2VA，而 B 路与 --ref-audio 硬互斥，日志不报错但成片换嗓。若渲染链已 export DRAMA_H3_FORCE_ROUTE=ref 且用 ps 实测 --ref-audio 存在，则本项可忽略；否则开片前先补上（L26） | `$HOME/drama-series-agent/templates/凡人修仙传/run/EP005.episode-run.jsonl → ref_characters/ref_voices (L26)` |
| 关键帧重出时效 | ✅ | 与基线 EP005.manifest.jsonl 逐行比对：1 镜提示词改动，关键帧均已重出（SHOT-012） | `$HOME/drama-series-agent/templates/凡人修仙传/assets/keyframes/EP005.manifest.jsonl 逐行 vs EP005.manifest.jsonl (L23,L27)` |
| 渲染产物新鲜度 | ✅ | 21 镜产物与当前分镜指纹一致（render_sig 未变、done 全真） | `$HOME/drama-series-agent/templates/凡人修仙传/output/EP005/.shot-fingerprints.json → render_guard.shot_fingerprint 重算 (L22,L27)` |
| 关键帧指纹路径 | ✅ | 实证 21 镜指纹随 <EP>/ 关键帧变化，按集取图已生效；根目录仍遗留 21 张同名旧图（SHOT-001, SHOT-002, SHOT-003…），不影响 sig，建议后续清理避免歧义 | `assets/keyframes/<SHOT>.png vs assets/keyframes/EP005/<SHOT>.png → render_guard.shot_fingerprint 实证 (E5)` |
| 实测段与批量集同构 | ✅ | 首行 prompt sha1 同为 cca682edb1aa（1343 字），实测段与批量集同构 | `EP005PROBE.episode-run.jsonl vs EP005AUD.episode-run.jsonl 首行 video_prompt sha1 (L22)` |
| 交付件链完整性 | ✅ | 交付链齐备，EP005_成片.mp4 与 master.final.mp4 同 inode；交付件语义：master.mp4 裸母版 → master.sub.mp4 烧字幕 → master.final.mp4 混 BGM | `$HOME/drama-series-agent/templates/凡人修仙传/output/EP005 → master.mp4 / .sub / .final / .srt / .ass / *_成片.mp4 (L16,L24)` |
| 字幕时间轴 | ✅ | 21 条字幕，末条 end 157.40s / 成片 158.56s，零越界 | `$HOME/drama-series-agent/templates/凡人修仙传/output/EP005/EP005.srt vs master.final.mp4 Duration (L24)` |
| 历史 ASR 遗留 | ⚠️ | 最近报告 fix_ep005_asr_after.json：命中 <90% 4 镜（SHOT-001=81.2%, SHOT-009=2.9%, SHOT-014=61.2%, SHOT-017=84.1%）；续写（asr/ref >1.15）1 镜（SHOT-009=1.43x）；开片前确认这些遗留是否已修复，命中率 100% 也要看 asr_chars 比值 | `$HOME/drama-series-agent/logs/fix_ep005_asr_after.json → hit_rate / asr_chars:ref_chars (L17,L21)` |
| BGM 电平 | ✅ | 目标 -32.0 dBFS，在可听区间（≥ -35） | `$HOME/drama-series-agent/scripts/gen_bgm.py → TARGET_BGM_RMS_DBFS (E1)` |
| 字幕标签口径 | ✅ | SRT 含「画外音」0 处，收尾脚本口径 none，一致 | `$HOME/drama-series-agent/templates/凡人修仙传/output/EP005/EP005.srt + finalize_ep005.sh → --vo-label (L24)` |
| 脚本 stdin 安全 | ✅ | 43 处 ffmpeg/ffprobe 调用均带 stdin 防护，heredoc 无 </dev/null 覆盖 | `scripts/*.py + src/**/*.py 的 subprocess 调用；scripts/*.sh 的 heredoc (L19,L28)` |
| Shell 脚本隐患 | ✅ | 未发现 pkill -f 自匹配与 sudo 提权行 | `scripts/*.sh 静态扫描 (L4,L7,L8,L10)` |
| 模型名可识别 | ✅ | vendor=Custom、model=MiniMax-M3.1-Flash、云端模型无需注入 enable_thinking=False，判定链实证通过 | `load_llm_settings → detect_vendor / prepare_request_kwargs (L6) \| https://api.iamhc.cn/v1` |
| 画布 32 对齐 | ✅ | 800×448 均为 32 倍数 | `config.json → render.width/height (L9)` |
| GPU 同池并发 | ✅ | VRAM 已用 33.1 / 余 62.9 GiB；llama-server=1 / sd-cli=0；同池无并发冲突 | `/sys/class/drm/card*/device/mem_info_vram_* + pgrep -x (L3,L5,L11)` |
| LLM 双层端点 | ✅ | 8080 真模型 / 18090 docproxy 均 /health ok（应用侧填 18090） | `GET 127.0.0.1:8080/health + 18090/health (E2)` |
| llama 面板托管 | ✅ | 1 个 llama-server 均由面板托管 | `/proc/<pid>/status PPid → 父进程 cmdline (E3)` |
| 经验库覆盖 | ✅ | 登记 L1~L30 + 5 条项目经验共 35 条：自动检测 24 条、人工守则 11 条；本次 22 个经验检查项全部产出 | `drama/lesson_checks.py → LESSON_REGISTRY` |

## 三、验收结论

深度审查不可用（模型调用失败：TimeoutError: ）。6 项需注意，但无阻断性问题，可在出片同时观察。

## 四、二次确认

> 本验收单**不会自动开拍**。确认方式二选一：

1. 导播台右上角「🔍 验收开片」面板 → 底部「✅ 确认开始生成」；
2. 对话里说「验收通过，开始生成 EP005」。

放行凭据有效期 30 分钟，且绑定当前分镜指纹；重新构建分镜后需重新验收。

## 五、交给 WorkBuddy 深度复核（可选）

把下面整段贴进 WorkBuddy 会话，它会读原始文件做逐镜复核并直接改代码/资源：

```text
读取 $HOME/drama-series-agent/docs/acceptance/20261109-160154-EP005-acceptance.md 与 $HOME/drama-series-agent/templates/凡人修仙传/run/EP005.episode-run.jsonl，
对 EP005 做开片前深度验收：逐镜检查 video_prompt 与关键帧是否匹配、角色是否串味、
字幕/时长节奏是否合理；修复后重新跑一次验收，通过再开拍。
```

## 六、证据路径

- 分镜：`$HOME/drama-series-agent/templates/凡人修仙传/run/EP005.episode-run.jsonl`
- 关键帧：`$HOME/drama-series-agent/templates/凡人修仙传/assets/keyframes/`
- 剧本：`$HOME/drama-series-agent/templates/凡人修仙传/剧集/EP005/screenplay.md`
- 采集快照：`$HOME/drama-series-agent/run/preflight/pf_20261109_155924/raw.json`

## 七、经验库覆盖（已知正向经验 / 坑）

开片验收已把 `tasks/lessons.md` 的 L1~L30 与 5 条项目实证经验登记进
`drama/lesson_checks.py::LESSON_REGISTRY`。`auto` 项由上面的检查表自动判定，
`manual` 项是操作守则 / 前端调试 / 创作决策，无法用只读检查判定，开片前人工确认。

| 编号 | 经验 | 方式 | 对应检查项 / 说明 |
|---|---|---|---|
| L1 | 动手前先查已有技能与工具 | 人工守则 | 外部系统操控先查 ~/.workbuddy/skills，属操作习惯 |
| L2 | 稳定性指标不能用瞬时特征位置 | 人工守则 | 项目外 doctor-day-v2 的画面对比指标，本管线无对应产物 |
| L3 | 显存够 ≠ 能跑更大分辨率 | 自动检测 | `gpu_pool` |
| L4 | pkill -f 会匹配自己的命令行 | 自动检测 | `shell_hazards` |
| L5 | 启动占显存服务前先扫并行任务 | 自动检测 | `gpu_pool` |
| L6 | 配置类故障先做判定链实证 / 模型名必须可识别 | 自动检测 | `vendor_detect` |
| L7 | 含 sudo 的脚本要在无终端环境启动 | 自动检测 | `shell_hazards` |
| L8 | 后台进程组回收 + pkill 自匹配复发 | 自动检测 | `shell_hazards` |
| L9 | 前端能力表 / 分辨率必须 32 像素对齐 | 自动检测 | `resolution_align` |
| L10 | 前端能力表新增字段须与后端同轮重启 | 人工守则 | 前端调试守则，验收单提示；裸链兜底靠 code review |
| L11 | Vulkan device lost ≠ 分辨率过高 | 自动检测 | `gpu_pool` |
| L12 | 重排表单后必须验证保存链路 | 人工守则 | 需 CDP 交互回放，非只读检查范围 |
| L13 | 被中断的验证等于没验证，续做先补跑 | 人工守则 | 会话级守则 |
| L14 | 删模块要连带清干净派生符号 | 人工守则 | 需 tsc --noEmit，不在开片验收内 |
| L15 | 不可选的后端选项是负债 | 人工守则 | UI 设计决策 |
| L16 | 先确认看的是哪个文件再判缺陷 | 自动检测 | `deliverables` |
| L17 | 台词密度够 ≠ 防幻听 / 提示词三件套 | 自动检测 | `dialogue_triplet`, `long_shot_audio`, `asr_history` |
| L18 | 提示词修不了 H3 长镜原生音频 | 自动检测 | `long_shot_audio` |
| L19 | ffmpeg 继承 stdin → 后台 SIGTTIN 全组 STOP | 自动检测 | `ffmpeg_stdin` |
| L20 | 用户拒掉的方案要立刻从后续口径摘掉 | 人工守则 | 需人工同步 lessons / 方案文档 / automation prompt；TTS 路线已被否决 |
| L21 | ASR 命中率 100% ≠ 没有续写 | 自动检测 | `asr_history` |
| L22 | 批量 GPU 链启动前比对实测段与全量集 prompt 指纹 | 自动检测 | `probe_fingerprint`, `render_freshness`, `kf_fingerprint_blindspot` |
| L23 | 修提示词不能只在末尾追加约束 | 自动检测 | `prompt_conflict`, `kf_freshness` |
| L24 | 画外音字幕类反馈先分三层再判 | 自动检测 | `vo_ratio`, `subtitle_timeline`, `deliverables`, `vo_label` |
| L25 | 参考图会独立注入锁脸套话 | 自动检测 | `kf_lockface` |
| L26 | 清空 ref_characters 后必须强制 A 路 | 自动检测 | `route_voice_anchor` |
| L27 | 批量改 jsonl 只替换目标行 | 人工守则 | 补丁脚本写法，需 diff 审查；验收单提示 |
| L28 | heredoc 传脚本时禁加 </dev/null | 自动检测 | `ffmpeg_stdin` |
| L29 | 经验不能只写在 md，必须变成开片前可执行检查 | 人工守则 | auto/manual 分层，manual 不假装自动检测；本模块与验收单第七段即其落地 |
| L30 | 修隐患时检测口径与历史缓存必须一起迁移 | 人工守则 | 检查要验行为不验源码文本；改指纹/ID 口径必须迁移缓存，否则修复反触发全量重渲；补丁 dry-run→apply→幂等复跑 |
| E1 | BGM 电平过低近似无 BGM | 自动检测 | `bgm_level` |
| E2 | 8080 真模型 / 18090 docproxy 两层端点 | 自动检测 | `llm_layers` |
| E3 | llama 实例必须经 MCSManager 面板托管 | 自动检测 | `panel_managed_llama` |
| E4 | 响度一致性 / 参考图张数 / 单段上限随画布 | 自动检测 | `loudness`, `refpic`, `duration` |
| E5 | 关键帧指纹路径缺 <EP> 子目录 | 自动检测 | `kf_fingerprint_blindspot` |

合计 35 条：自动检测 24 条、人工守则 11 条。

> 人工守则（开片前逐条确认）：
> - **L1** 动手前先查已有技能与工具 — 外部系统操控先查 ~/.workbuddy/skills，属操作习惯
> - **L2** 稳定性指标不能用瞬时特征位置 — 项目外 doctor-day-v2 的画面对比指标，本管线无对应产物
> - **L10** 前端能力表新增字段须与后端同轮重启 — 前端调试守则，验收单提示；裸链兜底靠 code review
> - **L12** 重排表单后必须验证保存链路 — 需 CDP 交互回放，非只读检查范围
> - **L13** 被中断的验证等于没验证，续做先补跑 — 会话级守则
> - **L14** 删模块要连带清干净派生符号 — 需 tsc --noEmit，不在开片验收内
> - **L15** 不可选的后端选项是负债 — UI 设计决策
> - **L20** 用户拒掉的方案要立刻从后续口径摘掉 — 需人工同步 lessons / 方案文档 / automation prompt；TTS 路线已被否决
> - **L27** 批量改 jsonl 只替换目标行 — 补丁脚本写法，需 diff 审查；验收单提示
> - **L29** 经验不能只写在 md，必须变成开片前可执行检查 — auto/manual 分层，manual 不假装自动检测；本模块与验收单第七段即其落地
> - **L30** 修隐患时检测口径与历史缓存必须一起迁移 — 检查要验行为不验源码文本；改指纹/ID 口径必须迁移缓存，否则修复反触发全量重渲；补丁 dry-run→apply→幂等复跑


> 本验收单由确定性检查 + 本地模型生成，全程只读，未改动剧本、分镜与配置。
---

> 许可：CC0-1.0，公共领域贡献，无任何限制。

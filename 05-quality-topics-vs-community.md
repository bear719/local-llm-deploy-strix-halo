# 05 · 五个质量专题：本地方案 vs 社区经验

把「视频生成质量」拆成五个互不干扰的专题，逐个对照社区做法，
标注哪些值得抄、哪些纯属浪费预算。

- 引擎：sd.cpp（Vulkan）build-vk2，MiniMax-H3 `vid_gen`（FL2VA diffusion + audio-vae + qwen3vl_32b 文本编码器）
- 画幅：768×1344 竖屏 9:16，24 fps，单段 39 帧 / 1.625 s
- 采样：12 步 `res_multistep`，`cfg_scale=1.0`，simple scheduler

---

## 0. 五个最关键结论（TL;DR）

1. **本管线的 `-r` 就是 MiniMax-H3 原生 Ref2VA**
   （`sd-cli --help` 原文："reference image for Flux Kontext or MiniMax-H3 Ref2VA (can be used multiple times)"，
   代码里硬校验上限 9 张）。
   社区热议的 IP-Adapter / InstantID / PuLID / PhotoMaker / ConsisID **全部只作用于图像域**
   （SD1.5 / SDXL / Flux），**对 H3 视频 DiT 无效** —— 不要往这个方向投入。

2. **身份一致性提升的最短路径不是换引擎，是把「每镜 2 张参考图」升级为「角色身份库」。**
   Ref2VA 支持最多 **9 图 + 3 视频 + 3 音频**，当前只用了 2 张（镜头首帧 + 1 张定妆照）。
   `--ref-audio`（角色音色）通道代码里已实现，但清单里没配。

3. **`cfg_scale=1.0` 是蒸馏模型配置，负向词基本失效**（没有有效的无条件下分支）。
   社区两个独立专题都这么判定。现有 28 项负向词从未做过 A/B 量化 ——
   **在验证之前，不应把预算花在「继续加长负向词」上**。

4. **RIFE 插帧在段间硬切处被社区实证否决**（自动检测硬切并跳过；强行插 1–4 帧产生鬼影，
   比硬切更怪）。正确方向是 `--init-img` 帧锁 + 音频 crossfade 从 0.084 s 提到 0.15–0.2 s
   + 切点选在动作停顿处。RIFE 的正确用途是**段内补帧**（16→24 fps）。

5. **存在一个与本地架构同构的社区方案**：`ComfyUI-H3-Motion-Context-MultiRef`
   （latent 尾帧直链 + masked context），其续段边界恰好是 39 / 90 / 141 / 192 帧 ——
   与 sd.cpp 的单段上限完全对齐。这是段间运动连贯性的根治方向，但需换整个 ComfyUI 生态。

---

## 1. 专题一：分段衔接

| | 本地方案 | 社区经验 |
|---|---|---|
| 段间连续性 | 硬切；`--ref-video` 重叠已实测关闭（裁掉的都是真实画面，非"重演"） | **latent 直链**：把采样器 latent 尾帧直接喂下一段 masked-context 节点；续段边界 39/90/141/192 帧 |
| 参考回灌 | 曾用解码视频回灌 → 逐代质量漂移 + 显存暴涨（+6k token） | 「把 VAE 解码视频回灌 = 逐代质量漂移」，规范做法是传 latent |
| 帧插值 | 未用 | RIFE/FILM 在硬切处被实证否决；正确用途是段内补帧 |
| 音频接缝 | acrossfade **0.084 s**（2 帧） | 硬切标准 **0.15–0.2 s**，equal-power（半余弦）曲线，统一 48 kHz；「音桥」= 下段音频提前 0.3–0.5 s 淡入 |
| 转场设计 | 无 | 切点落在动作停顿/对话间隙；叠 0.2 s 黑场/闪白遮挡；转场时长 ≈ 单镜时长 ×15% |

**落地顺序**

1. 立即可做：续段默认 `--init-img`；crossfade 0.084 → **0.15 s**；段边界对齐到动作停顿帧
2. 短期：保留 `-r` 面部锚定但**不再用 `--ref-video`**
3. 长期（根治）：latent 直链，需换 ComfyUI 生态，**仅当硬切观感无法接受时再投入**

---

## 2. 专题二：口型匹配

| | 本地方案 | 社区经验 |
|---|---|---|
| 路线 | H3 联合生成（画面 + 语音同出） | 社区共识：**「先 TTS 再对口型」在可控场景更稳**（能精确控音素与停顿） |
| 现有问题 | 口型对不上、吐字不清、闭唇仍有嘴动 | 源于联合生成的弱口型分支 |
| 可用工具 | 无 | **Wav2Lip-ONNX**（ONNXRuntime + Vulkan EP，iGPU 原生，唯一零 CUDA 依赖）；**MuseTalk 1.5**（MIT，~4 GB，只重绘嘴区）；LatentSync v1.5（6.5 GB，中文改善明显） |
| 大基座 | — | HunyuanVideo-Avatar 13B / MultiTalk：96 GiB 装得下但 iGPU 未验证、极慢（10 s ≈ 60 min），**不推荐** |

**被忽略的原生能力**：sd.cpp 有 `--ref-audio` / `--ref-video-audio`，
代码里也已实现「读 `data/cast/{系列}/voices/角色名.wav`」的函数。
**先确认清单里 `ref_voices` 到底配没配** —— 这是零成本的音色锚定。

**落地顺序**

1. 零成本：启用 `ref_voices`（每角色一条干净语音样本）→ 用 Ref2VA 的音频通道锚定音色与说话风格
2. 若口型仍不达标：MuseTalk 1.5 → 不行退 Wav2Lip-ONNX/Vulkan EP
3. 商用 API 仅作应急 fallback

> 音色迁移的固有限制：**极短语音（<1 s）迁移最弱**。
> 实测 0.61 s 台词音色明显滑向默认。对策是把台词拆开、各自给足时长。

---

## 3. 专题三：文字 / 图形伪影

| | 本地方案 | 社区经验 |
|---|---|---|
| 抑制手段 | 28 项负向词 + 空白表面正向锚定 | 负向词规律：**只对模型已理解的视觉概念有效，越长越被稀释，应短而具体**；`cfg=1.0` 蒸馏模型下调 CFG 压制不可行 |
| 检测 | 无（靠人眼） | **RapidOCR**（ONNX，纯 CPU ~5.8 s/大图，比 PaddleOCR 快 10×）；关键帧降采样 + 置信度 >0.5 + **多帧投票** |
| 修补 | 无 | LaMa（~182 ms/帧，规则纹理背景）/ OpenCV Telea（~46 ms/帧） |
| 构图 | prompt 锚定 | 竖屏会议室场景滋生地排序：**投影屏 > 笔记本屏幕 > 白板 > PPT > 胸牌/文件**；让这些表面失焦/出画/背光最稳 |

**推荐方案：OCR 质检闭环**

```
每段渲染完 → 进 ffmpeg 封装前 → 抽关键帧 → RapidOCR 检测 → 多帧投票
       → 标记「含文字段」→ 换 seed 重渲染该段 → 仍偶发则 Telea/LaMa 局部修补
```

零大模型，纯 ffmpeg + OpenCV + RapidOCR。
同时把负向词从 28 项精简到 ~12 项高命中词。

---

## 4. 专题四：脸型一致性

见 [04-segment-repetition-and-seed.md](04-segment-repetition-and-seed.md) 的路线取舍，以及
[02-ep002-root-causes.md](02-ep002-root-causes.md) 的根因 A/B/C。

要点：

| 手段 | 效果 |
|---|---|
| 关键帧必须吃静态机位（`angle_zh`） | 影响面最大 |
| 关键帧侧与视频侧的人物锚**分开判定**（起幅 vs 完整动作） | 修「落幅自由生脸」 |
| 道具三级锚定（图像锚 / 文字锚 / 无锚） | 修「一镜三样」 |
| 人物三态（faces / silhouette / none），**背影判定排第一** | 修「空镜画出脸」与「背影被抹掉」 |
| 身份库（3–4 图/角色，Ref2VA 上限内） | 跨镜漂移降至次要问题 |

---

## 5. 专题五：手部细节

| | 本地方案 | 社区经验 |
|---|---|---|
| 抑制 | 仅负向词（疑无效） | **MediaPipe Hands**（CPU ~30 FPS，~6 MB）：21 点关键点 + 置信度，可判「坏手」（置信度 <0.5、五指尖两两距离过近 = 融合、可数指尖 ≠ 5） |
| 根因 | — | 训练数据手部样本少 + VAE 潜空间压缩吞高频指节细节 + 帧间注意力把错误结构当锚点放大 |

**推荐方案**

1. **MediaPipe 坏帧检测 → 换 seed 重渲染该段**（最轻量、性价比最高）
2. **正向手部锚定替代负向词**：前置 `five fingers clearly separated, anatomically correct hand, natural finger curl`
3. **景别规避**：把「手部特写」改成「虚化手部 + 清晰面部/文件」，从源头减少手部面积

---

## 6. 横向总览

| 专题 | 本地评级 | 更优解 | 增量投入 | 预期改善 |
|---|---|---|---|---|
| 分段衔接 | 硬切（音频已 crossfade） | init-img 帧锁 + crossfade 0.15 s + 切点工程化 | 极低 | 接缝从「声画都断」到「仅画面硬切」 |
| 口型匹配 | 联合生成，偏弱 | ref-audio 音色锚定 → MuseTalk → Wav2Lip | 低→中 | 吐字清晰度与同步率显著提升 |
| 文字伪影 | 28 项负向词，无质检 | RapidOCR 多帧投票 + 重渲染/修补 | 低 | 乱码镜头从「靠肉眼漏检」到「自动拦截」 |
| 脸型一致性 | 2 图 Ref2VA | 身份库（3–4 图/角色）+ 好帧回收 | 中 | 跨镜漂移降至次要问题 |
| 手部细节 | 仅负向词（疑无效） | MediaPipe 检测 + 重渲染闭环 + 正向锚定 | 低 | 偶发畸形大幅减少 |

---

## 7. 分级行动清单

### P0 — 零/极低成本（不动渲染引擎）

1. `audio_crossfade_seconds`：0.084 → **0.15**
2. 启用 `ref_voices`（零成本音色锚定）
3. 负向词 28 项 → ~12 项高命中精简版
4. 建 RapidOCR + MediaPipe 质检脚本（纯 Python，挂在出片后）
5. 每角色身份库素材（3–4 张）

### P1 — 小投入

6. 多 anchor 支持（Ref2VA 9 图上限内）
7. MediaPipe 坏帧 → 换 seed 重渲染闭环接入 runner
8. RapidOCR 含文字段 → 重渲染 / Telea 修补
9. MuseTalk 1.5 试点 1–2 个对白特写
10. Inswapper / CodeFormer 后处理归一化（对存量镜头先试，见效再推广）

### P2 — 需决策的大投入

11. ComfyUI + H3 latent 直链迁移（仅当 P0/P1 后硬切仍不可接受）
12. 商用口型 API fallback 通道

### 不建议做

| 不做 | 原因 |
|---|---|
| IP-Adapter / InstantID / PuLID / PhotoMaker 套 H3 | 只作用于图像域 SD1.5/SDXL/Flux，对视频 DiT 无效 |
| RIFE 在段间硬切处插帧 | 鬼影比硬切更怪 |
| 调高 `cfg_scale` 压伪影 | 蒸馏模型，引入过饱和 |
| H3 角色 LoRA 训练 | compute-bound，收效低 |
| HunyuanVideo-Avatar / MultiTalk 大基座本地部署 | iGPU 未验证、极慢 |
| 继续加长负向词 | `cfg=1.0` 下基本失效，越长越被稀释 |

---

## 8. 必做验证实验：负向词到底生不生效

社区两个独立专题都判定「`cfg=1.0` 蒸馏模型负向词失效」，
但**本管线的负向词从未做过 A/B 量化**。

**设计**

| 项 | 内容 |
|---|---|
| 变量 | 同 seed、同 prompt、同段数；A = 现有 28 项 / B = 空 / C = 12 项精简 |
| 样本 | 各跑 3 段 |
| 度量 | RapidOCR 检出文字帧占比（文字伪影率）；MediaPipe 坏手帧占比；人工抽帧观感 |
| 判据 | 若 A ≈ B → 负向词无效 → 预算全转检测+重渲染闭环；若 A < B → 保留并精简 |
| 成本 | 3 组 × 3 段 × 37 分钟 ≈ **5.5 小时**（可排夜班） |

> ★ 这个实验的价值不在于结论是哪个 —— 而在于**它只花 5.5 小时就能终结一个长期靠猜的问题**。

---

## 9. 来源

- sd.cpp 源码与 `--help`（`video.cpp` Ref2VA/FL2VA 互斥、`-r` 多次使用、`--ref-audio`、`--cfg-scale` 默认 7.0）
- ComfyUI-H3-Motion-Context-MultiRef（H3 专用 latent 续段，边界 39/90/141/192 帧）
- VideoHelperSuite / H3 多参考工作流；RunComfy H3 Ref2VA 工作流；Com-Org H3 包
- Wan2.2 FLF2V/VACE、LTX-Video 多关键帧 extend（首尾帧串联思路）
- RIFE/FILM 硬切检测行为（社区实测共识）
- MuseTalk 1.5（MIT）、LatentSync v1.5、Wav2Lip-ONNX、EchoMimicV2、HunyuanVideo-Avatar、MultiTalk
- IP-Adapter FaceID / InstantID / PuLID / Infinite-You / StoryMaker / Magic-Me / ConsisID(CVPR25)
- RapidOCR vs PaddleOCR 实测、LaMa、ADetailer
- MediaPipe Hands 文档

> ⚠ 免责：以上社区效果数据来自公开仓库/评测/讨论，**未经本机复测**。
> 本机相关结论（39 帧上限、A/B 路互斥、overlap 实测、种子 42）来自本地实测。

---

**许可**：CC0-1.0，公共领域贡献，无任何限制。

# MiniMax-H3（视频 + 立体声联合生成）

用 sd.cpp（Vulkan）在本机生成带音轨的视频。40.85 GB 权重全部落 BIOS carve-out，
**host RAM 占用 0**，与 llama.cpp 显存记账完全独立。

## 四组件（缺一不可）

| 参数 | 文件 | 体积 |
|---|---|---|
| `--diffusion-model` | `minimax_h3_fl2va-Q4_K_M.gguf` | 17.5 GiB |
| `--llm`（文本编码器） | `qwen3vl_32b_minimax_h3-Q4_K_M.gguf`（官方）或 Sakura abliterated Q5_K_M（uncensored） | 17.0 GiB |
| `--vae` | `minimax_h3_video_vae_fp16.safetensors` | 4.85 GiB |
| `--audio-vae` | `minimax_h3_audio_vae_fp32.safetensors` | 0.56 GiB |

## 硬约束

- 宽高向上对齐 **32 的倍数**
- 帧数必须是 **17k+5**（5 / 22 / 39 / 56 / 73 / 90），最小 5
- **固定 24 fps**（传其他值被覆盖）
- **cfg 1.0**（蒸馏引导）
- 建议 `--diffusion-fa`（扩散内 flash attention）与 `--rng cpu`

## 实测（本机）

| 档位 | 耗时 |
|---|---|
| 480×480×5 帧（试参） | 51.3 s |
| 864×480×56 帧 @ 20 步 | **723 s** |
| 864×480×56 帧 @ 8 步 + Turbo LoRA | **356 s（2.03×）** |

- 日志铁证：`total params memory size = 40854.23MB (VRAM 40854.23MB, RAM 0.00MB)` → host RAM 0
- VRAM 峰值 **75.1 GB**（含 llama.cpp 33.5 GB）；GTT 全程 1.7 GB 未动
- **4 步在 sd.cpp 下画质崩坏，勿用**；≤8 步会告警
- fp16 视频 VAE 无偏色（与 Wan2.2 相反）→ 不需要 `--tensor-type-rules "^vae\.=f32"`

## 加速 LoRA（Turbo）

- 源：`larryvrh/MiniMax-H3-Turbo-Lora` 的 **0.73 GiB** safetensors（10 GiB 的 `.bin` 是训练 checkpoint，别下）
- 键名必须转成 kohya 风格 `lora.model.diffusion_model.<tensor>.weight.lora_down/up`
  （源为 diffusers `blocks.N.attn.qkv_proj.lora_A/B.weight`）
- 默认启用；`SD_NO_LORA=1` 关闭走 20 步

## 文本编码器切换

```bash
H3_ENCODER=uncensored ./start.sh "提示词" ...   # 默认，Sakura abliterated Q5_K_M
H3_ENCODER=official   ./start.sh "提示词" ...   # 原官方 Qwen3-VL-32B Q4_K_M
```

> ⚠️ **已知路径偏差**：`start.sh` 默认找 `$MD/uncensored/Sakura-...gguf`，
> 但实际文件当前落在 `$MD/` 根目录。用前二选一：
> `mkdir -p $MD/uncensored && ln -sf ../Sakura-MiniMax-H3-TextEncoder-Uncensored-Q5_K_M-17.00GiB.gguf $MD/uncensored/`
> 或把脚本里 `LLM_FILE` 指到实际路径。

## 输出容器

sd.cpp 写 **AVI/MJPEG（视频）+ pcm_s16le 32 kHz 立体声（同容器）**，脚本自动转 H.264 MP4：

- 必须 `-vf "scale=in_range=full:out_range=full"`（源为全范围 yuvj420p，否则二次偏色）
- 必须 `-nostdin` / `</dev/null`（后台或管道环境下 ffmpeg 会等待 stdin 永久挂起）
- 系统无 ffmpeg 时用 `imageio_ffmpeg` 自带静态二进制

视频模型选型与内存池隔离详见 [`docs/06-video-pipeline.md`](../../docs/06-video-pipeline.md)。

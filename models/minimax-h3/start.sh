#!/bin/bash
# MiniMax-H3 视频+立体声音频联合生成 —— sd.cpp Vulkan 后端
#
# 用法: ./start-minimax-h3.sh ["提示词"] [宽] [高] [帧数] [offload] [步数]
#   例: ./start-minimax-h3.sh "a kitten surfs on a wave" 864 480 56 "" 8
#   加第 5 个参数 offload 则启用 --offload-to-cpu（权重放 host RAM，本机 host RAM 紧张，慎用）
#   第 6 个参数为采样步数，默认 8（配合 Turbo LoRA）；置 SD_NO_LORA=1 可关闭 LoRA 走 20 步
# 环境变量: H3_ENCODER=uncensored(默认,社区abliterated)|official(原版权重)
#   实测：20步 723s -> 8步+LoRA 356s（2.03×，画质保持）；4 步在 sd.cpp 下崩坏，勿用
#
# 硬件约束（来自 sd.cpp docs/minimax_h3.md）:
#   - 宽高向上对齐到 32 的倍数（864x480 = 27x15）
#   - 帧数向上对齐到 17k+5 网格，最小 5（5/22/39/56/73/90）
#   - 固定 24 fps（传其他值会被覆盖）
#   - cfg 1.0（蒸馏引导）；video flow shift=12，audio shift=3（内部映射）
#   - 建议加 --diffusion-fa（扩散模型内用 flash attention）与 --rng cpu
#
# 四组件（缺一不可）:
#   --diffusion-model  minimax_h3_fl2va-Q4_K_M.gguf        17.5 GiB
#   --vae              minimax_h3_video_vae_fp16.safetensors 4.85 GiB
#   --audio-vae        minimax_h3_audio_vae_fp32.safetensors 0.56 GiB
#   --llm              qwen3vl_32b_minimax_h3-Q4_K_M.gguf  17.0 GiB
#
# 产物: sd.cpp 写 <base>.avi（MJPEG 视频 + pcm_s16le 32kHz 立体声，
#       ★ 本版本音频已直接 mux 进 AVI 容器，不再旁路写 .wav），
#       本脚本自动转 H.264 MP4（音轨自动保留）。
#
# 实测（2026-10-08，本机 480x480x5帧 / 864x480x56帧）:
#   - 日志 `total params memory size = 40854.23MB (VRAM 40854.23MB, RAM 0.00MB)`
#     → 40.85 GB 权重全落 carve-out，host RAM 占用 0
#   - VRAM 峰值 75.1 GB（含 llama.cpp 33.5 GB），GTT 纹丝不动
#   - fp16 视频 VAE 无偏色（与 Wan2.2 不同，无需强制 f32）
#   - 5帧档总耗时 51.3s；56帧档采样 ~32.7 s/it × 20 步

set -e
SD=$HOME/sdcpp-src/build-vk2/bin/sd-cli
MD=$HOME/models/minimax-h3
OUT_DIR=$HOME/WorkBuddy/调试本地模型/out
FF=$(ls $HOME/.workbuddy/binaries/python/envs/default/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-* 2>/dev/null | head -1)

PROMPT="${1:-A cute ginger kitten surfs on a tropical ocean wave, riding a white surfboard. Cinematic tracking shot, realistic water, bright sunlight, smooth motion. Add upbeat surf-rock background music with drums and guitar.}"
W="${2:-864}"; H="${3:-480}"; F="${4:-56}"; OFFLOAD="${5:-}"; STEPS="${6:-8}"
LORA_DIR="$MD/loras"; LORA_NAME=h3-turbo4
TAG=$(date +%Y%m%d-%H%M%S)

# 文本编码器选择（2026-10-16 接入社区 abliterated 版，默认启用）:
#   uncensored = Sakura-MiniMax-H3-TextEncoder-Uncensored-Q5_K_M-17.00GiB.gguf
#                （webmp3/Sakura-MiniMax-H3-Uncensored-GGUF，基于 llmfan46 的
#                 abliterated Qwen3-VL-32B-Instruct；仅换文本编码器，去噪器/VAE 不动）
#   official   = 原官方 Qwen3-VL-32B 编码器（qwen3vl_32b_minimax_h3-Q4_K_M.gguf）
# 回滚官方版：H3_ENCODER=official ./start-minimax-h3.sh "提示词" ...
H3_ENCODER="${H3_ENCODER:-uncensored}"
case "$H3_ENCODER" in
  uncensored) LLM_FILE="$MD/uncensored/Sakura-MiniMax-H3-TextEncoder-Uncensored-Q5_K_M-17.00GiB.gguf" ;;
  official)   LLM_FILE="$MD/qwen3vl_32b_minimax_h3-Q4_K_M.gguf" ;;
  *) echo "[ERROR] H3_ENCODER 仅支持 official|uncensored，当前: $H3_ENCODER -> 修复: 改正环境变量"; exit 1 ;;
esac

for f in minimax_h3_fl2va-Q4_K_M.gguf minimax_h3_video_vae_fp16.safetensors \
         minimax_h3_audio_vae_fp32.safetensors; do
  [ -f "$MD/$f" ] || { echo "[ERROR] 缺组件: $MD/$f"; exit 1; }
done
[ -f "$LLM_FILE" ] || { echo "[ERROR] 缺编码器($H3_ENCODER): $LLM_FILE"; exit 1; }
[ -x "$SD" ] || { echo "[ERROR] 缺二进制: $SD"; exit 1; }
mkdir -p "$OUT_DIR"

EXTRA=()
[ "$OFFLOAD" = "offload" ] && EXTRA+=(--offload-to-cpu)
[ -n "${SD_VAE_F32:-}" ] && EXTRA+=(--tensor-type-rules "^vae\.=f32")

# 加速 LoRA（Turbo 4-step 蒸馏）：默认启用，置 SD_NO_LORA=1 关闭
# ★ 键名必须为 lora.model.diffusion_model.*（由 scripts/h3_lora_to_sdcpp.py 转换）
LORA_ARGS=(); LORA_TAG=""
if [ -f "$LORA_DIR/$LORA_NAME.safetensors" ] && [ "${SD_NO_LORA:-}" != "1" ]; then
  LORA_ARGS=(--lora-model-dir "$LORA_DIR"); LORA_TAG=" <lora:$LORA_NAME:1.0>"
  [ "$STEPS" -lt 8 ] && { echo "[WARN] 步数 $STEPS < 8：实测 sd.cpp 下 4 步画质崩坏，建议 ≥8"; }
fi

echo "=== 生成前 ==="
rocm-smi --showmeminfo vram 2>/dev/null | grep Used
rocm-smi --showmeminfo gtt  2>/dev/null | grep Used
free -m | head -2
echo "参数: ${W}x${H} ${F}帧 24fps cfg1.0 ${STEPS}步${LORA_TAG:+ +加速LoRA} 编码器:$H3_ENCODER${EXTRA[*]:+ 额外:${EXTRA[*]}}"

RAW="$OUT_DIR/${TAG}-mmh3.mp4"
time "$SD" -M vid_gen \
  --diffusion-model "$MD/minimax_h3_fl2va-Q4_K_M.gguf" \
  --vae             "$MD/minimax_h3_video_vae_fp16.safetensors" \
  --audio-vae       "$MD/minimax_h3_audio_vae_fp32.safetensors" \
  --llm             "$LLM_FILE" \
  --cfg-scale 1.0 -W "$W" -H "$H" --video-frames "$F" --fps 24 --steps "$STEPS" \
  --diffusion-fa --rng cpu "${LORA_ARGS[@]}" "${EXTRA[@]}" \
  -p "$PROMPT$LORA_TAG" \
  --output "$RAW"

AVI="$RAW.avi"; WAVF="$RAW.wav"; MP4="$OUT_DIR/${TAG}-mmh3.mp4"
if [ -n "$FF" ] && [ -f "$AVI" ]; then
  AIN=(); [ -f "$WAVF" ] && AIN=(-i "$WAVF" -c:a aac -b:a 192k -shortest)
  # ★ -nostdin / </dev/null 必不可少：后台或管道环境下 ffmpeg 会因等待 stdin 而永久挂起
  "$FF" -y -v error -nostdin -i "$AVI" "${AIN[@]}" \
        -vf "scale=in_range=full:out_range=full" \
        -c:v libx264 -pix_fmt yuv420p -crf 18 -movflags +faststart "$MP4" < /dev/null
  "$FF" -y -v error -nostdin -i "$AVI" -vf "select=eq(n\,$((F/2))),scale=in_range=full:out_range=full" \
        -vframes 1 -pix_fmt rgb24 -update 1 "$OUT_DIR/${TAG}-mmh3-preview.png" < /dev/null
  echo "MP4(含音轨): $MP4"
  [ -f "$WAVF" ] && echo "原始音轨: $WAVF"
  echo "首帧预览: $OUT_DIR/${TAG}-mmh3-preview.png"
else
  echo "[WARN] 未找到静态 ffmpeg，保留 AVI: $AVI"
fi

echo "=== 生成后 ==="
rocm-smi --showmeminfo vram 2>/dev/null | grep Used
rocm-smi --showmeminfo gtt  2>/dev/null | grep Used
free -m | head -2
echo "=== 判据 ==="
echo "  VRAM 上涨 = sd.cpp 占 carve-out（预期）；GTT 不变 = 未走 GTT（预期）"
echo "  llama.cpp 应仍可用: curl -s http://127.0.0.1:8080/health"

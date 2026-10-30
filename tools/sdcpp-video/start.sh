#!/bin/bash
# sd.cpp 视频生成 —— Vulkan 后端，与现有 llama.cpp 共存
#
# 用法: ./start-sdcpp-video.sh ["提示词"] [宽] [高] [帧数] [步数]
#   例: ./start-sdcpp-video.sh "a ginger cat walking on grass" 832 480 33 20
#
# 原理: sd.cpp 走 Vulkan DEVICE_LOCAL -> 落在 BIOS UMA carve-out(96 GiB)，
#       VRAM 记账与 llama.cpp 的 33 GiB 互不挤占（实测 VRAM_used 各自独立增长）。
#
# 【关键参数，勿删】
#   --tensor-type-rules "^vae\.=f32"
#       Wan2.2 的 VAE 在高压缩比下 FP16 解码会溢出 -> 画面整体偏绿、蓝通道被压死
#       (实测 R/G/B = 142/208/9)。强制 VAE 走 f32 后恢复 (105/102/51)。
#   --cfg-scale 5.0
#       Wan 官方推荐值；默认 7.0 会过饱和。
#   --steps 20
#       默认值。低于 10 步流匹配轨迹不收敛，也会加重偏色。
#
# 产物: sd.cpp 实际写出的是 AVI/MJPEG 容器（后缀无关），本脚本自动转 H.264 MP4。
#
# 【权重依赖】三个文件共 8.1 GB，2026-10-08 按少爷要求移入回收站以释放磁盘。
#   需要时:  ./start-sdcpp-video.sh --download
#   来源:    QuantStack/Wan2.2-TI2V-5B-GGUF + city96/umt5-xxl-encoder-gguf (hf-mirror.com)
#   部署经验: ~/.workbuddy/skills/sdcpp-vulkan-video/SKILL.md

set -e
SD=$HOME/sdcpp-src/build-vk2/bin/sd-cli
MODEL_DIR=$HOME/models/wan
OUT_DIR=$HOME/WorkBuddy/调试本地模型/out
# imageio_ffmpeg 自带的静态 ffmpeg（系统未装 ffmpeg）
FF=$(ls $HOME/.workbuddy/binaries/python/envs/default/lib/python3*/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-* 2>/dev/null | head -1)

# 一键重下三个权重（约 8.1 GB，三路并行；断点续传）
if [ "${1:-}" = "--download" ]; then
  mkdir -p "$MODEL_DIR" && cd "$MODEL_DIR"
  B=https://hf-mirror.com
  curl -L -C - --retry 5 --retry-delay 3 -o Wan2.2-TI2V-5B-Q4_K_M.gguf \
    "$B/QuantStack/Wan2.2-TI2V-5B-GGUF/resolve/main/Wan2.2-TI2V-5B-Q4_K_M.gguf" &
  curl -L -C - --retry 5 --retry-delay 3 -o Wan2.2_VAE.safetensors \
    "$B/QuantStack/Wan2.2-TI2V-5B-GGUF/resolve/main/VAE/Wan2.2_VAE.safetensors" &
  curl -L -C - --retry 5 --retry-delay 3 -o umt5-xxl-encoder-Q4_K_M.gguf \
    "$B/city96/umt5-xxl-encoder-gguf/resolve/main/umt5-xxl-encoder-Q4_K_M.gguf" &
  wait
  echo "下载完成:"; ls -lh
  exit 0
fi

PROMPT="${1:-a ginger cat walking on grass, cinematic lighting}"
W="${2:-832}"; H="${3:-480}"; F="${4:-33}"; STEPS="${5:-20}"
TAG=$(date +%Y%m%d-%H%M%S)

for f in Wan2.2-TI2V-5B-Q4_K_M.gguf Wan2.2_VAE.safetensors umt5-xxl-encoder-Q4_K_M.gguf; do
  if [ ! -f "$MODEL_DIR/$f" ]; then
    echo "[ERROR] 缺模型文件: $MODEL_DIR/$f"
    echo "        -> 执行 $0 --download 自动重下（约 8.1 GB，三路并行）"
    exit 1
  fi
done
if [ ! -x "$SD" ]; then
  echo "[ERROR] 缺二进制: $SD -> 重新执行 cmake --build build-vk2 -j16"
  exit 1
fi
mkdir -p "$OUT_DIR"

echo "=== 生成前 ==="
rocm-smi --showmeminfo vram 2>/dev/null | grep "Used"
rocm-smi --showmeminfo gtt  2>/dev/null | grep "Used"
free -m | head -2
echo "参数: ${W}x${H} ${F}帧 ${STEPS}步 cfg5.0 VAE=f32"

# sd.cpp 只写 AVI，先用 .avi 承接
RAW="$OUT_DIR/$TAG.avi"
time "$SD" -M vid_gen \
  --diffusion-model "$MODEL_DIR/Wan2.2-TI2V-5B-Q4_K_M.gguf" \
  --vae             "$MODEL_DIR/Wan2.2_VAE.safetensors" \
  --t5xxl           "$MODEL_DIR/umt5-xxl-encoder-Q4_K_M.gguf" \
  --vae-format wan --tensor-type-rules "^vae\.=f32" --vae-tiling \
  -p "$PROMPT" \
  -W "$W" -H "$H" --video-frames "$F" --steps "$STEPS" --cfg-scale 5.0 \
  --output "$RAW"

# AVI/MJPEG(yuvj420p 全范围) -> H.264 MP4，显式按全范围解释，避免二次偏色
MP4="$OUT_DIR/$TAG.mp4"
if [ -n "$FF" ] && [ -f "$RAW" ]; then
  "$FF" -y -v error -i "$RAW" -vf "scale=in_range=full:out_range=full" \
        -c:v libx264 -pix_fmt yuv420p -crf 18 -movflags +faststart "$MP4"
  "$FF" -y -v error -i "$RAW" -vf "select=eq(n\,$((F/2))),scale=in_range=full:out_range=full" \
        -vframes 1 -pix_fmt rgb24 -update 1 "$OUT_DIR/$TAG-preview.png"
  echo "MP4: $MP4"
  echo "首帧预览: $OUT_DIR/$TAG-preview.png"
else
  echo "[WARN] 未找到静态 ffmpeg，保留 AVI: $RAW"
fi

echo "=== 生成后 ==="
rocm-smi --showmeminfo vram 2>/dev/null | grep "Used"
rocm-smi --showmeminfo gtt  2>/dev/null | grep "Used"
free -m | head -2
echo "=== 判据 ==="
echo "  VRAM 上涨 = sd.cpp 占用 carve-out（预期）"
echo "  GTT 不变 / host available 未被吃光 = 未走 GTT（预期）"
echo "  llama.cpp(8080) 仍应可用: curl -s http://127.0.0.1:8080/health"

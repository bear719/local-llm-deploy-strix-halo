#!/usr/bin/env bash
# FastFlowLM (flm) NPU 服务启动脚本 —— 供 MCSManager 面板通用实例调用
#
# 用途：在维持 96 GiB UMA + Vulkan + MTP 主链路不变的前提下，
#       把 XDNA2 NPU 作为「任务级旁路工人」挂到 8219，专接杂活。
# 配套：tools/docproxy.py 的 NPU_UPSTREAM 分流补丁（默认关闭）。
#
# ★ 铁律：必须前台 exec，切勿 nohup / & 后台化。
#   MCSManager 靠前台主进程判定实例存活，后台化会导致面板显示「已停止」
#   并无法暂停/重启；gpu_arbiter 也会把非托管进程当野进程误判。
#
# 2026-11-08 落地变更：
#   - FLM 升级到 v1.0.12（ubuntu26.04 deb）
#   - 默认模型改为 lfm2.5-it:1.2b（0.94 GiB / 无思考链 / penalty 0）
#   - 默认模型根目录改为 /home/<user>/models/flm（少爷约定：所有模型下载到 /home/<user>/models）
#     注意该路径下还要多一层 models/，真权重在 $FLM_MODEL_PATH/models/<模型名>/
#
# 面板实例建议配置（照抄 docproxy-18090 的结构，仅改以下字段）：
#   nickname      : flm-npu-8219
#   startCommand  : env /home/<user>/WorkBuddy/调试本地模型/start-flm-npu.sh
#   stopCommand   : ^c
#   type          : universal
#   processType   : general
#   ie / oe       : utf8
#   basePort      : 8219
#   eventTask.autoStart / autoRestart : true
#
# 用法（本地手工调试时）：
#   ./start-flm-npu.sh                          # 默认 lfm2.5-it:1.2b
#   MODEL_TAG=qwen3.5:0.8b ./start-flm-npu.sh   # 视觉旁路
#   EMBED=embed-gemma:300m ./start-flm-npu.sh   # 同时挂 embedding
#   ASR=1 EMBED=1 ./start-flm-npu.sh            # 同时挂 ASR + 默认 embedding
#
# 环境变量（全部可选）：
#   MODEL_TAG   模型标签，默认 lfm2.5-it:1.2b
#   PORT        监听端口，默认 8219（flm 自身默认是 52625）
#   HOST        监听地址，默认 0.0.0.0（必须显式，flm 默认只听 127.0.0.1）
#   PMODE       功耗档位，默认 balanced（默认档是 performance，混合机让预算给 iGPU）
#   CTX_LEN     上下文，默认 8192（NPU2 模型上限 32768，max_prefill_len 4096）
#   Q_LEN       NPU 队列长度，默认 4（NPU 全局互斥串行，队列过长只堆内存）
#   SOCKET      最大连接数，默认 8
#   EMBED       非空则加 --embed <值>；1 = 默认 embed-gemma:300m
#   ASR         非空则加 --asr <值>；1 = 默认 whisper-v3:turbo
#   FLM_MODEL_PATH  模型根目录，注意其下必须还有一层 models/
#   FLM_PRECHECK    置 1 时启动前跑一次 flm validate
#   MIN_MEMAVAIL_MIB 启动前 host RAM 水位线，默认 4096 MiB

set -u

MODEL_TAG="${MODEL_TAG:-lfm2.5-it:1.2b}"
PORT="${PORT:-8219}"
HOST="${HOST:-0.0.0.0}"
PMODE="${PMODE:-balanced}"
CTX_LEN="${CTX_LEN:-8192}"
Q_LEN="${Q_LEN:-4}"
SOCKET="${SOCKET:-8}"
EMBED="${EMBED:-}"
ASR="${ASR:-}"
MIN_MEMAVAIL_MIB="${MIN_MEMAVAIL_MIB:-4096}"
FLM_PRECHECK="${FLM_PRECHECK:-1}"

# ---- 本地附加能力开关（面板 startCommand 属主 root，改不了，用这个文件打开）----
# 只接受白名单键，且「面板显式传了就不用文件的」，避免覆盖 MODEL_TAG/FLM_MODEL_PATH。
# 关掉某项：把对应行删掉或注释掉，然后面板重启实例。
FLM_CONF="${FLM_CONF:-/home/<user>/WorkBuddy/调试本地模型/flm-npu.conf}"
if [ -f "$FLM_CONF" ]; then
  while IFS='=' read -r _k _v; do
    _k="$(printf '%s' "$_k" | tr -d '[:space:]')"
    _v="$(printf '%s' "$_v" | sed 's/[[:space:]]*$//')"
    case "$_k" in
      EMBED|ASR|Q_LEN|SOCKET|CTX_LEN|PMODE)
        [ -n "${!_k-}" ] || export "$_k=$_v"
        ;;
    esac
  done < <(grep -vE '^[[:space:]]*(#|$)' "$FLM_CONF" 2>/dev/null)
  echo "[OK] 已加载附加配置 $FLM_CONF (EMBED=$EMBED ASR=$ASR)"
fi

# ---- flm 三坑（项目 MEMORY.md 第六节，2026-10-07 实测） ----
# ① ROCm/HIP 环境变量会干扰 XDNA 栈初始化，必须清掉
unset ROCM_PATH HIP_PATH LD_LIBRARY_PATH
# ② 国内直连 HuggingFace 不通，走镜像
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
# ③ 模型根路径必须显式注入，否则 flm list --filter installed 返回 No models found
#    注意：该路径下还要多一层 models/，真权重在 $FLM_MODEL_PATH/models/<模型名>/
export FLM_MODEL_PATH="${FLM_MODEL_PATH:-/home/<user>/models/flm}"

# ---- 前置检查 ----
if ! command -v flm >/dev/null 2>&1; then
  echo "[ERROR] 找不到 flm 可执行文件 -> 检查 PATH 或 /opt/fastflowlm 安装" >&2
  exit 1
fi

if [ ! -e /dev/accel/accel0 ] && [ ! -e /dev/accel0 ]; then
  echo "[ERROR] 找不到 /dev/accel0 -> 检查 amdxdna 驱动与 BIOS NPU 开关" >&2
  exit 1
fi

if [ ! -d "$FLM_MODEL_PATH/models" ]; then
  echo "[ERROR] 模型目录不存在: $FLM_MODEL_PATH/models" >&2
  echo "        提示：FLM_MODEL_PATH 指向根目录，其下必须还有一层 models/" >&2
  exit 1
fi

# host RAM 是 NPU 与所有 HIP 栈共享的 30.47 GiB 池，低水位时不启动，避免全局 OOM
avail_kib="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
avail_mib=$((avail_kib / 1024))
if [ "$avail_mib" -lt "$MIN_MEMAVAIL_MIB" ]; then
  echo "[ERROR] MemAvailable ${avail_mib} MiB < 水位线 ${MIN_MEMAVAIL_MIB} MiB，拒绝启动" >&2
  echo "        依据：2026-10-08 实测 HIP 分配 20 GiB 时 avail 仅 494 MiB -> 全局 OOM" >&2
  exit 1
fi

if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
  echo "[ERROR] 端口 $PORT 已被占用 -> 先停掉占用进程，或改 PORT" >&2
  exit 1
fi

if [ "$FLM_PRECHECK" = "1" ]; then
  echo "[检查] flm validate（NPU 栈自检）"
  if ! timeout 40 flm validate; then
    echo "[ERROR] NPU 栈自检失败 -> 检查 amdxdna / 固件 / render 组权限" >&2
    exit 1
  fi
fi

# ---- 组装参数 ----
ARGS=(serve "$MODEL_TAG"
      --host "$HOST"
      --port "$PORT"
      --pmode "$PMODE"
      --ctx-len "$CTX_LEN"
      --q-len "$Q_LEN"
      --socket "$SOCKET")
[ -n "$EMBED" ] && ARGS+=(--embed "$EMBED")
[ -n "$ASR" ]   && ARGS+=(--asr "$ASR")

echo "[OK] flm ${ARGS[*]}"
echo "[OK] FLM_MODEL_PATH=$FLM_MODEL_PATH   HF_ENDPOINT=$HF_ENDPOINT"
echo "[OK] MemAvailable=${avail_mib} MiB   上游主链路 8080 不受影响"

# ★ 前台阻塞，进程替换成 flm 本身
exec flm "${ARGS[@]}"

# 许可：CC0-1.0，公共领域贡献，无任何限制。

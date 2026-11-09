# prompt cache / context checkpoint 落 GPU carve-out —— 改造与实测

> 日期：2026-11-09 23:00–23:40
> 起因：少爷观察到 host RAM 所剩无几（可用 6.3 GB、swap 已用 13.9 GB），要求把 KV 相关数据放显存，
> 因为 VRAM 还有 62.6 GiB 空着。
> 结论：**改造成功并在生产生效。host 侧从 8.40 GB 降到 0.42 GB，prompt cache 与 checkpoint 全部落进
> 96 GiB 的 BIOS UMA carve-out。**

---

## 一、先纠正一个概念

**KV 本体早就在显存里。** 启动日志明确：

```
Vulkan0 KV buffer size = 2720.00 MiB    ← KV cache（-c 262144 全额预分配）
Vulkan0 RS buffer size =  188.44 MiB    ← SSM recurrent state
```

吃 host RAM 的不是 KV，而是**为「切走后还能复用」而序列化出来的副本**，共三条来源：

| # | 来源 | 数据量 | 证据 |
|---|---|---:|---|
| ① | `--cache-ram -1` = **字节无上限**（`server-task.h:614` `limit_size = (mib < 0 ? 0 : ...)`），只剩 `limit_tokens = n_ctx = 262144` 兜底 | 1–2.5 GB | 日志 `cache token limit (262144, est: 262144) reached, removing oldest entry (size = 792.746 MiB)` |
| ② | `--ctx-checkpoints` 默认 **32 个/槽**（`common/common.h:641`），每个 100–190 MiB | ≈3.7 GB | `-cms 8192` 下 262144/8192 = 32，正好撑满 |
| ③ | `Vulkan_Host` 的 model/compute staging buffer | 1.04 GB | 上游请求 `HOST_VISIBLE\|HOST_COHERENT\|HOST_CACHED` → 命中 heap0 = **GTT**（吃 host） |

实测现场（改造前）：

```
free -m         total 31205 / used 24867 / available 6337 / swap used 13872
llama-server    VmRSS 8.40 GB   RssAnon 8.39 GB   VmSwap 3.38 GB   ← 已被换出 3.4 GB
VRAM            33.37 / 96.00 GiB
GTT             3.46 GiB
```

---

## 二、为什么「直接加个参数」做不到

`server_prompt_data` 与 `common_prompt_checkpoint` 存的是：

```cpp
std::vector<uint8_t> main;   // server-task.h:589
std::vector<uint8_t> data_tgt;  // common.h:1185
```

**纯 CPU 堆**，llama.cpp 没有任何参数能把它放到 GPU 上。

但有一条现成通道：Vulkan 的 **host-visible buffer**（`ggml_vk_host_malloc`，`ggml-vulkan.cpp:8554`）
返回的指针 **CPU 可直接 memcpy**，而物理位置由所选 memory type 决定。本机的 memory 表：

| type | heap | flags | 归属 |
|---|---|---|---|
| 2 | heap0 (42.16 GiB) | HOST_VISIBLE \| HOST_COHERENT | **GTT，吃 host RAM** |
| **3 / 4** | **heap1 (84.32 GiB, DEVICE_LOCAL)** | **DEVICE_LOCAL \| HOST_VISIBLE \| HOST_COHERENT** | **carve-out，不吃 host** |
| 5 / 6 | heap0 | HOST_VISIBLE \| HOST_COHERENT \| HOST_CACHED | GTT |

上游只请求第 2、5 类 → 永远落 GTT。**必须显式带 `DEVICE_LOCAL` 才能命中 type 3/4。**

---

## 三、改造内容（三处，约 200 行）

### 1. `common/prompt-buffer.h`（新增，header-only）

无状态 allocator `ggml_prompt_allocator<T>` + 类型别名 `ggml_prompt_bytes`：

```cpp
using ggml_prompt_bytes = std::vector<uint8_t, ggml_prompt_allocator<uint8_t>>;
```

`allocate()` 先试 GPU buft，失败回落 `::operator new`；`deallocate()` 查表决定
`ggml_backend_buffer_free` 还是 `::operator delete`。

**关键设计：allocator 无状态**（所有实例等价），所以 `std::vector` 的拷贝/移动/swap 语义不变，
下游 `.data()` / `.size()` / `.resize()` / `.clear()` **一行都不用改**。

### 2. 类型替换（2 个结构体）

```cpp
// common/common.h:1185
ggml_prompt_bytes data_tgt;   // 原 std::vector<uint8_t>
ggml_prompt_bytes data_dft;

// tools/server/server-task.h:589
ggml_prompt_bytes main;       // 原 std::vector<uint8_t>
ggml_prompt_bytes drft;
```

`data_spec` 保持原生 vector —— `common_speculative_get/set_state` 的签名锁死了 `std::vector<uint8_t>&`。

### 3. `ggml-vulkan.cpp`：新增 `Vulkan_HostDL` buffer type

- `ggml_vk_host_malloc(device, size, prefer_device_local)` —— 加参数，默认仍是上游 GTT 行为
- `ggml_backend_vk_host_dl_buffer_type()` —— 首次请求
  `DEVICE_LOCAL|HOST_VISIBLE|HOST_COHERENT`（= type 3/4），失败再回落 GTT
- 实现 `ggml_backend_vk_reg_get_proc_address`（上游是 `NULL`），暴露
  `"ggml_backend_vk_host_dl_buffer_type"`
- `server-context.cpp` 在 `prompt_cache` 创建前取用它并打印落点

---

## 四、踩到的坑：全局切换会让 decode 掉 46%

第一版图省事，直接改 `ggml_vk_host_malloc` 的默认请求列表（全局 DEVICE_LOCAL）。结果：

| 项 | 上游 | 全局 carve-out |
|---|---:|---:|
| decode | 76.3 t/s | **41.4 t/s（−46%）** |
| GTT | 3.46 GiB | 0.15 GiB |
| VRAM | 33.35 GiB | 35.18 GiB |

**根因**：`Vulkan_Host` 的 **compute buffer（528 MiB）** 也被搬到了 carve-out 的
**uncached** 内存（type 3/4 没有 `HOST_CACHED` 位）。它在推理路径上被频繁访问，
uncached 直接拖垮 decode。

**修正**：只让显式请求 `prefer_device_local` 的分配走 carve-out，也就是**只给
prompt cache / checkpoint 用**，compute / model / output buffer 全部维持上游 GTT。
修正后 decode 回到 68–72 t/s（与关闭改造的对照组 71–74 t/s 差异在波动内）。

---

## 五、实测结果

### 落点确认

```
load_model: prompt/checkpoint state buffer: GPU host-visible (Vulkan_HostDL) [n_reg=2 HostDL=yes]
```

### 内存归属（3 条 27.5K 前缀全部缓存后）

| 项 | 改造前 | 阶段①（CPU 堆 + cache-ram 1024） | **阶段②（HostDL + cache-ram 8192）** |
|---|---:|---:|---:|
| VmRSS | 8.40 GB | 1.70 GB | **0.55 GB** |
| RssAnon | 8.39 GB | 1.64 GB | **0.46 GB** |
| VmSwap | 3.38 GB | 0 | **0** |
| host available | 6.34 GB | 13.01 GB | **13.8 GB** |
| VRAM | 33.37 GiB | 33.38 GiB | **35.55 GiB（+2.2）** |
| GTT | 3.46 GiB | — | **2.10 GiB（基本不动）** |

**关键判据**：3 条 27.5K 前缀（约 1.8 GB）让 **VRAM 涨了 1.78 GiB，GTT 只涨 50 MiB** ——
数据确实进了 carve-out，不是换了个地方吃 host RAM。

### 复用效果（27.5K 前缀，三个「应用」轮转 a/b/c）

```
a1  prompt_n=27508  cache_n=    0  prefill=29.41s   ← 冷
b1  prompt_n=27508  cache_n=    0  prefill=29.68s   ← 冷
a2  prompt_n=    4  cache_n=27504  prefill= 0.68s   ← 命中
b2  prompt_n=    4  cache_n=27504  prefill= 0.68s   ← 命中
c1  prompt_n=27508  cache_n=    0  prefill=29.79s   ← 冷
a3  prompt_n=    4  cache_n=27504  prefill= 0.69s   ← 命中
```

**29.4 s → 0.68 s（43×）**。对比阶段①（cache-ram 1024）同组测试是 `cache_n=0 / 30.6 s`
**完全不命中** —— 因为两条 27.5K 各约 600 MiB，1024 装不下，A 被 LRU 踢掉。

### 代价：命中时 prefill 慢 0.6 s

| 落点 | 命中耗时 | 原因 |
|---|---:|---|
| GTT（cached） | 0.06 s | 主机缓存可读 |
| **HostDL（uncached）** | **0.68 s** | carve-out 的 type 3/4 无 `HOST_CACHED`，约 0.65 GB/s |

443 MiB 反序列化从 0.06 s 变成 0.68 s。相对 29.4 s 的全量重算仍可忽略。

### 未被影响的部分

- **prefill 冷态：929.8 t/s**（历史 935–940，一致）
- **decode：68.3–71.9 t/s**（基线 76.3，对照 CPU 堆组 71.3–74.4，差异在波动内）

---

## 六、当前生产配置

| 项 | 值 |
|---|---|
| `--cache-ram` | **8192**（不再受 host RAM 约束） |
| `--ctx-checkpoints` | 8 |
| `-cms` | 8192 |
| `-c` / `-np` | 262144 / 1（未动） |
| 落点 | `Vulkan_HostDL`（carve-out） |
| 脚本 | `start-qwen36-35b-a3b.sh:173-176` |

### 容量边界

`limit_tokens = 262144` 仍是硬上限（不是字节限制）。按 27.5K/条算：

- 可同时驻留 **9 条 27.5K** 前缀（247.5K token）
- 或 **3 条 81K**
- 对应 VRAM 增量约 **5.5 GiB**（8192 MiB 池上限内），VRAM 余量 60 GiB，无压力

### 回滚（三级，成本递增）

```bash
# ① 只把落点切回 CPU 堆（最轻，推荐做 A/B 用）
touch /tmp/prompt_buf_off && 面板重启
#    → 日志出现 "prompt/checkpoint state buffer: CPU heap"

# ② 落点不变、只缩小 cache 池
CACHE_RAM_MIB=1024 面板重启

# ③ 二进制级回滚（彻底撤销本次改造）
cp build-vk4/bin/.bak-20261109/{libllama-server-impl.so,libllama-common.so*,libllama.so*} \
   build-vk4/bin/ && 面板重启

# ④ 让所有 Vulkan host 分配回 GTT（只用于验证 HostDL 无关性）
GGML_VK_HOST_BUF_GTT=1
```

### 备份清单

| 文件 | 内容 |
|---|---|
| `start-qwen36-35b-a3b.sh.bak.20261109-hostram` | 方案 B 之前的脚本 |
| `start-qwen36-35b-a3b.sh.bak.20261109-gpuprompt` | HostDL 生效版脚本 |
| `build-vk4/bin/.bak-20261109/` | 改造前 6 个二进制/共享库 |
| `build-vk4/bin/llama-server.bak.20261109-preGPUprompt` | 改造前 `llama-server` |

---

## 七、遗留与建议

1. **命中时 0.68 s 可否优化**：可选把 prompt cache 落 GTT（cached，0.06 s）而 checkpoint 落 carve-out。
   但会重新占用约 0.6 GB host / 条，权衡后当前方案更符合「host 只剩 14 GB」的约束。
2. **`--ctx-checkpoints 8` 是否够**：27.5K 前缀只需 4 个（8192 间隔）。若日常跑 100K+，建议回到 16。
3. **`-np` 仍是另一条路**：多槽能让 KV 原生常驻 device-local，checkpoint 也更少。
   但 draft-MTP 的 cross-slot 串扰（上游 PR #28123）未验，本次未动。
4. **上游同步**：本次改动全在本机 fork（`common/prompt-buffer.h`、`ggml-vulkan.cpp` 的 `get_proc_address`、
   两处结构体类型）。上游若升级，需重新套用；`prompt-buffer.h` 本身与上游无冲突。

---

> 许可：CC0-1.0，公共领域贡献，无任何限制。

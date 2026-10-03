#!/usr/bin/env python3
"""轻量 GGUF 探针：只解析 header + KV + tensor 名，不读权重数据。

用途：确认 qwen4exp 模型用的是 joined 表布局（per_layer_token_embd）
还是 per-head 布局（ple_ngram_embd.N），决定是否支持 --ngram-on-disk。
用法: python3 gguf_probe.py <file.gguf> [--tensors]
"""
import struct
import sys

GGUF_TYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 8: "Q5_0", 9: "Q5_1",
              10: "Q8_0", 11: "Q8_1", 12: "Q2_K", 13: "Q3_K", 14: "Q4_K",
              15: "Q5_K", 16: "Q6_K", 17: "Q8_K", 18: "IQ2_XXS", 24: "BF16",
              28: "Q4_K_P", 101: "ROCmFP4_FAST"}


def r_str(f):
    n = struct.unpack("<Q", f.read(8))[0]
    return f.read(n).decode("utf-8", "replace")


def r_val(f, t):
    if t == 0:      # UINT8
        return struct.unpack("<B", f.read(1))[0]
    if t == 1:      # INT8
        return struct.unpack("<b", f.read(1))[0]
    if t == 2:      # UINT16
        return struct.unpack("<H", f.read(2))[0]
    if t == 3:      # INT16
        return struct.unpack("<h", f.read(2))[0]
    if t == 4:      # UINT32
        return struct.unpack("<I", f.read(4))[0]
    if t == 5:      # INT32
        return struct.unpack("<i", f.read(4))[0]
    if t == 6:      # FLOAT32
        return struct.unpack("<f", f.read(4))[0]
    if t == 7:      # BOOL
        return struct.unpack("<B", f.read(1))[0]
    if t == 8:      # STRING
        return r_str(f)
    if t == 9:      # ARRAY
        et = struct.unpack("<I", f.read(4))[0]
        n = struct.unpack("<Q", f.read(8))[0]
        out = [r_val(f, et) for _ in range(min(n, 64))]
        for _ in range(max(0, n - 64)):
            r_val(f, et)
        return out
    if t == 10:     # UINT64
        return struct.unpack("<Q", f.read(8))[0]
    if t == 11:     # INT64
        return struct.unpack("<q", f.read(8))[0]
    if t == 12:     # FLOAT64
        return struct.unpack("<d", f.read(8))[0]
    raise ValueError(f"未知 GGUF 值类型 {t}")


def main():
    path = sys.argv[1]
    show_tensors = "--tensors" in sys.argv
    with open(path, "rb") as f:
        assert f.read(4) == b"GGUF", "不是 GGUF 文件"
        ver = struct.unpack("<I", f.read(4))[0]
        n_tensors, n_kv = struct.unpack("<QQ", f.read(16))
        print(f"文件: {path}")
        print(f"GGUF 版本: {ver}  张量数: {n_tensors}  KV 数: {n_kv}")
        kv = {}
        for _ in range(n_kv):
            k = r_str(f)
            t = struct.unpack("<I", f.read(4))[0]
            kv[k] = r_val(f, t)
        print("\n--- 关键 KV ---")
        for k in sorted(kv):
            if any(s in k for s in ("ple", "general.architecture", "general.name",
                                    "block_count", "nextn", "expert", "embedding_length",
                                    "vocab_size", "file_type", "quantize")):
                print(f"  {k} = {kv[k]}")
        print("\n--- PLE 布局判定 ---")
        joined = per_head = False
        ple_bytes = 0
        for _ in range(n_tensors):
            name = r_str(f)
            nd = struct.unpack("<I", f.read(4))[0]
            dims = struct.unpack("<" + "Q" * nd, f.read(8 * nd))
            typ = struct.unpack("<I", f.read(4))[0]
            off = struct.unpack("<Q", f.read(8))[0]
            if name == "per_layer_token_embd.weight":
                joined = True
                rows, w = dims[1], dims[0]
                # 按 4bit/行字节粗算：fp4 约 w/2 字节每行
                print(f"  [joined] {name} dims={dims} type={GGUF_TYPES.get(typ, typ)} offset={off}")
            elif name.startswith("ple_ngram_embd"):
                per_head = True
                ple_bytes += 1
                if show_tensors:
                    print(f"  [per-head] {name} dims={dims} type={GGUF_TYPES.get(typ, typ)}")
            elif show_tensors:
                print(f"  {name} dims={dims} type={GGUF_TYPES.get(typ, typ)}")
        if joined:
            print("  => joined 布局：支持 --ngram-on-disk / --model-ple")
        elif per_head:
            print(f"  => per-head 布局（{ple_bytes} 个头表）：--ngram-on-disk 会被忽略（no-op）")
        else:
            print("  => 未找到 PLE 张量，该模型无 n-gram 表")


if __name__ == "__main__":
    main()

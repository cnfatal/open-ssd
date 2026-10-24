# 通用透传：`ossd dev passthru`

把一条任意厂商命令原样发给设备，用于调试、抓包对照和一次性查询。
开卡流程不需要它，日常也不需要。

## 1. 功能范围

一条命令按 BOT（Bulk-Only Transport，USB 批量传输协议） 三阶段执行：发命令容器 → 数据/无数据阶段 → 读完成包。
内容原样传递，不自动分包、不改写、不加许可状态。

```text
支持    任意 8 位 opcode、NSID、CDW10–15，或直接给 64B SQE 文件
方向    由调用者指定（IN / OUT / 无数据）
```

## 2. 参数

| 参数 | 说明 |
| --- | --- |
| `--opcode N` | 8 位 opcode（C0/C1/C2…） |
| `--cdw10..--cdw15 N` | 命令 DWORD，十进制或 `0x` 十六进制 |
| `--sqe FILE` | 直接给 64 字节 SQE（Submission Queue Entry，提交队列项），忽略上面的字段 |
| `--data-in N` / `--data-out FILE` / `--no-data` | 三选一 |
| `--output-dir DIR` | 保存请求、实收数据、完成包、result.json |
| `--vid/--pid/--serial` | 选择目标，默认 `152d:0583` |
| `--timeout-ms N` | 单次 I/O 超时，默认 5000 |
| `--trace` | 额外写 `events.jsonl` |
| `--recover-bot` | 执行一次 class reset → clear IN → clear OUT，不重发命令 |
| `--dry-run` | 只构帧，不访问设备 |

## 3. 使用示例

```sh
# 读 Flash ID（SMI 私有命令），需要 root
sudo python3 -m ossd dev passthru --opcode 0xc2 --cdw10 512 --cdw12 0x40 --cdw13 1 \
  --data-in 2048 --output-dir work/flash-id

# 带 payload 的写命令，仅生成帧
python3 -m ossd dev passthru --opcode 0xc1 --data-out payload.bin --dry-run

# 无数据命令
python3 -m ossd dev passthru --opcode 9 --no-data --dry-run

# 使用已有 SQE 文件
python3 -m ossd dev passthru --sqe command.sqe.bin --data-in 1024 --dry-run
```

`--dry-run` 只打印将要发送的内容；实际执行时去掉它并给 `--output-dir`。

## 4. 结果与退出码

输出目录里会保存：

```text
request.sqe.bin     实际发送的 64 字节
data-in.bin         IN 方向实收字节
completion.bin      原始完成包
result.json         actual、CSW 原始字节、residue、NVMe 状态
```

结果里保留四层状态（见 [protocol.md](../02-controller/sm2263xt/protocol.md) 第 9.4 节）：
实际字节数、CSW（Command Status Wrapper，命令状态封装）、residue、NVMe（Non-Volatile Memory Express，非易失性存储接口规范） status。IN 方向只在 residue 非零时继续读完成包并
标 `UNKNOWN`；不会因此封锁下一次调用。

```text
退出码 0  严格完成
       1  参数/文件错误
       2  打开设备失败
       3  清理失败
       5  设备失败或异常诊断
```

## 5. 限制

```text
- JMS Admin 封装的单次长度字段只有 24 位
- 不支持同一笔命令双向传输，也不支持独立 metadata
- SQE 的 flags/CID 与 CDW2–9 必须为 0
- 这是桥的命令封装，不是任意 PCIe 报文
- 没有整命令 deadline、时钟检查或自动重试
- 日志是尽力记录，没有 fsync 屏障
```

需要超时/重试策略时由调用方自己控制。

## 6. 来源

封装格式参考 smartmontools 的 JMicron 实现（`scsinvme.cpp`），并做过早停修正。
命令语义由调用者负责——工具只保证"命令编码与数据传输"。

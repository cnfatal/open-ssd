# YMTC TAS 系列

本文记录 SM2263XT 原厂包中 YMTC TAS 系列的配置条目。项目示例设备选用 `YMN09TC1B1OC6C` 配置行。

## 1. Flash.SET 型号条目

V0209 的 Flash.SET 共 6 条 YMTC 记录：

| 别名 | 型号 | ID | CE（Chip Enable，片选） | die/CE | 说明 |
| --- | --- | --- | --- | --- | --- |
| A0 | YMN09TC1B1HC6C | `9B C4 28 49 20 00` | 4 | 1 | 2Tbit |
| A1 | YMN09TC1B1JC6C | `9B C5 29 49 20 00` | 4 | 2 | 4Tbit |
| A2 | YMN09TC1B1OC6C | `9B C5 29 49 20 00` | 8 | 2 | 8Tbit ← 项目示例设备 |
| A3 | YMN09TC1B1MC6C | `9B C6 2A 49 20 00` | 4 | 4 | 8Tbit |
| A4 | YMN09TC1B1HCAD | `9B C4 28 49 30 00` | 4 | 1 | 2Tbit |
| A5 | YMN09TC1B1JCAD | `9B C4 29 49 30 00` | 4 | 1 | 2Tbit |

## 2. 型号命名结构

```text
YM N09 T C1B1 O C6C
│  │    │  │    │
│  │    │  │    └─ 封装/批次后缀
│  │    │  └────── 容量与 die 配置（H/J/O/M 对应不同档）
│  │    └───────── T = TLC
│  └────────────── 09 = 世代
└───────────────── YM = YMTC
```

**不要只凭型号名判断 CE 数**——以 Flash.SET 那一行的第 17/19 列（die/CE、CE）和
`C2/80` 实测为准。

## 3. 容量档位与拓扑

指封装总容量档，不是单 die 容量：

```text
2Tbit = 4 CE × 1 die
4Tbit = 4 CE × 2 die
8Tbit = 8 CE × 2 die
```

项目示例设备 16 die × 512 Gbit = 8192 Gbit = 8Tbit。

## 4. 同一 ID 的歧义

`9B C5 29 49 20 00` 同时出现在 A1（4 CE）和 A2（8 CE）——
**仅凭 ID 无法区分**，必须再读 `C2/80` 数实际 CE/die：

```text
矩阵 4×4，非零格数 = 实际 CE 数；每格的值 = 该 CE 上的 die 数
项目示例设备：4 通道 × CE0/CE2 = 8 格，每格 0x03（2 die） → 8 CE / 16 die → A2
```

配置与拓扑不匹配时，Pretest 的 `FlashConnectivity` 检查可能失败。

## 5. 本系列文档

| 文档 | 内容 |
| --- | --- |
| [x2-9060.md](x2-9060.md) | `9B C5 29` 对应配置：几何、SET 行、profile 与实测结果 |

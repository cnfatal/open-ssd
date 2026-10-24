# 固件类型与选择依据

原厂包包含多个修订和用途的固件。本文说明各类固件的职责，以及依据 ROM（Read-Only Memory，只读存储器） 标签、NAND（NOT AND，非与型闪存） ID 和拓扑选择输入的规则。

## 1. 四类文件的分工

```text
BootISP2263*.bin      复位后由 ROM 执行的第一段（18 KiB 左右）
MPISP2263.bin         主机上传的维护程序（91 KiB）
ISP2263XT_core*.bin   真正的工作固件（core1 128 KiB + core0 1 MiB）
ISP2263XT_RDT_core*   可靠性测试固件（可选，本流程不用）
```

它们不是同一层的东西：

```text
ROM ──(上传)──► MPISP ──(生成并写入)──► InfoBlock 里的 BootISP + Bank
                                              │
                                     复位 ────┘
                                       ▼
                                     ROM 读 InfoBlock → 执行 BootISP → 加载 Bank
```

## 2. 判据一：ROM 标签决定 BootISP

ROM 里最后几十字节有版本标签：

```text
地址 0x9FF0..0x9FFF： "2263ROM:SVN02777"
```

原厂按标签选对应修订：

| 标签 | 修订码 | 用哪份 BootISP |
| --- | --- | --- |
| `2263ROM:SVN00235` | AB | `BootISP2263A1.bin`（34816 B） |
| `2263ROM:SVN00350` | AC | `BootISP2263A2.bin`（18432 B） |
| `2263ROM:SVN02777` | AD | `BootISP2263A3.bin`（18432 B） |
| 无匹配且有 A4 特性位 | A4 | `BootISP2263A4.bin` |

项目示例设备读到 `SVN02777`，所以用 **A3**。

**不要用 Identify 的 `2777` 代替这个判断**——Identify 只报四位，ROM 标签是
完整字符串，两者不是一回事。

## 3. 判据二：颗粒 ID 决定 Flash.SET 行

Flash.SET 是一张表，每行描述一种颗粒：

```text
<名字>=<ID0..ID5>,<通道>,<位宽>,<页大小>,<总扇区>,<页/块>,<块数>,...
```

项目示例设备读到的 ID 是 `9B C5 29 49 20 00`。在表里匹配到两条：

```text
YMTC,4Tbit,YMN09TC1B1JC6C  CE=4  die/CE=2
YMTC,8Tbit,YMN09TC1B1OC6C  CE=8  die/CE=2   ← 项目示例设备
```

仅凭 ID 无法区分——同一颗 die 可以封装成 4 CE（Chip Enable，片选） 或 8 CE。要再用连通性测试
（`C2/80`）数实际有几个 CE、每个 CE 几个 die：

```text
项目示例设备：4 通道 × CE0/CE2 × 每格 2 die = 8 CE / 16 die  → 8Tbit 那一行
```

**选错的后果**：参数仅描述 4 个 CE，与实测 8 CE 不一致，Pretest 第一步
`FlashConnectivity` 就失败。

## 4. core0 的修订必须与 BootISP 一致

```text
A3 BootISP  → ISP2263XT_core0_A3.bin
A2 BootISP  → ISP2263XT_core0_A2.bin
```

core1 是通用的（`ISP2263XT_core1.bin`，128 KiB）。用错 core0 的表现是：
Pretest 全过、ISP 写入成功，但复位后固件不启动。

## 5. 包内 MPISP 与上传前处理

`MPISP2263.bin`（91136 B）与颗粒无关，所有修订共用。但**上传前要回填
SHA-256**：头部 `+0x294` 是 offset、`+0x298` 是长度，对
`[offset, offset+len)` 做 SHA-256，写进 `+0x2A0`。

```sh
ossd mpisp prepare $PKG/Firmware/MPISP2263.bin prep.bin
```

`ossd mpisp upload` 内部会自动做这一步。

## 6. 版本号

项目示例设备固件版本 `FWV0126A`，对应：

```text
MPISP    V0126A_MPISP
ISP      V0126A
CID 版本字段 "V0126A0"
```

包的版本必须与固件、CID 一致。混用不同版本的 MPISP 和 ISP，可能出现
"能写不能启动"。

## 7. 选择流程

```text
1. 读 ROM 标签 0x9FF0..0x9FFF        → 决定 BootISP A1/A2/A3
2. 读 C2/40 颗粒 ID + C2/80 拓扑     → 决定 Flash.SET 行
3. 按修订取 core0_A3 / core0_A2      → 与 BootISP 配对
4. core1 使用包内通用版本
5. 版本统一：MPISP / ISP / CID 同一个 FWV
6. 用哈希与长度校验文件没拿错
```

## 8. 校验清单

```sh
# 文件长度
ls -l $PKG/Firmware/
# 18432   bootisp-a3
# 91136   mpisp
# 131072  isp-core1
# 1048576 isp-core0-a3

# 内容自检（工具会打印）
ossd mpisp inspect $PKG/Firmware/MPISP2263.bin
ossd isp package --core0 ... --core1 ... --lightswitch ... --manufacturer YMTC --out DIR
```

更多细节见 [firmware-areas.md](firmware-areas.md) 与
[package.md](package.md)。

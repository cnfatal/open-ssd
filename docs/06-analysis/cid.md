# CID（LightSwitch）：4 KiB 的配置块

## 1. 结构与用途

4 KiB 的控制器身份与配置块。原厂流程在打包 ISP 时，用它覆盖 core0 末尾
4096 字节；同时它也作为 MPInfo 的前 4 KiB。

## 2. 子区与职责

| 偏移 | 内容 |
| --- | --- |
| `+0x008` | 固件版本（8 字节，空格补齐） |
| `+0x10C` | 序列号（20 字节） |
| `+0x128` | 型号（32 字节） |
| `+0x180` | 小字段（IdleGC 等） |
| `+0x200` | PCI ID、链路宽度、ASPM（Active State Power Management，活动状态电源管理）、NPSS |
| `+0x240` | NVMe（Non-Volatile Memory Express，非易失性存储接口规范） 功能位、VID（Vendor ID，厂商标识）/SSVID（Subsystem Vendor ID，子系统厂商标识）、HMB（Host Memory Buffer，主机内存缓冲）、IRST、PS4、FNA |
| `+0x300` | 安全开关、RPMB、ATA 透传、FW Auth |
| `+0x380` | 温度阈值、PS0/1/2/5 时钟表、SMART 温度 |
| `+0x3E0` / `+0x500` / `+0x510` | 零散覆盖字段 |
| `+0xE00` | RDT 配置（39 个字段 + 48 B 的 CH（Channel，通道）/CE（Chip Enable，片选） 矩阵） |

写入顺序决定字段覆盖结果：先子区，再 `+0xE00`，最后是一批"wrapper 直接写"，
后续写入覆盖此前内容；同一字段可能存在多个写入来源，**以最后写的为准**。

## 3. 已实测：working CID 只改 3 处

相对静态种子 `LightSwitch2263.bin`，原厂下发的 CID 只差 33 字节：

```text
+0x008  "FWREV  "               → "V0126A0"
+0x10C  "serial_numserial_num"  → "SN000000000000000000"
+0x128  "SMI2263XT"             → "SMI 2263XT"
```

三处都是"空格补齐、超长截断"。对应生成命令如下：

```sh
ossd cid identity --base LS.bin --version V0126A0 \
  --serial SN000000000000000000 --model "SMI 2263XT" --out cid-work.bin
```

结果与厂商包里的 CID **逐字节相同**。

注意 SN 是占位符，不是配置里的真实 SN；真实序列号在 MPInfo 里。

## 4. 时钟表与索引空间

三张表不是同一张：

```text
Pretest FlashClock   0..8 → 50/100/200/266/325/333/400/133…
PS Sys clock        13 项
PS LDPC / Flash     11 项：400/325/266/200/166/133/100/83/66/40/33 MHz
```

`FlashClock=3` 在 Pretest 表里是 **200 MHz**，不是 CSV 里第 4 项的 333 MHz。
把两张表混用会得到错误的频率。

## 5. 与 RDT 的关系

`+0xE00` 区域由 RDT 配置驱动（循环次数、ECC（Error Correction Code，纠错码） 阈值、失败阈值、
测试块数、温度上限、48 B 的 CH/CE 矩阵）。不开 RDT 时这段保持种子值。

## 6. 身份标识的构造

除上述三处，还有几个由 SN/配置派生的字段：

```text
8 字节标识    由 SN 构造
16 字节标识   由配置文本构造
3 字节 / 8 字节 独立输出
组合 16 字节   SN 覆盖配置后再生成
```

这些在正常开卡里由工具自动填；自定义 OUI/EUI64 时需分析这些派生字段。

# InfoBlock 分段布局与字段

InfoBlock 是主控启动时读的第一块数据。它把"引导代码、参数、坏块表、工作固件"
打包为连续镜像，按页存放。本文按页序说明各段的职责、来源与示例实测大小。

## 1. 示例页布局（原厂导出，101 页）

```text
页    段名        实测大小        来源
0     Boot 段 1   18,432 B       BootISP2263A3.bin（含 10 字节元数据补丁）
1     ParamTable  1,024 B        由 D + Flash.SET 生成
2     Boot 段 3   ≈6,144 B       Boot 文件偏移 0x3000 起
3     Boot 段 2   ≈6,144 B       Boot 文件偏移 0x1800 起
4     SeedTable   4,608 B        SeedTable2304.bin
5-6   OrgBad      32 KiB         原始坏块扫描（C1/91 + C2/85）
7-8   EraseBad    32 KiB         擦除复扫（C1/92 + C2/83）
9-10  TotalBad    32 KiB         合并后的坏块位图
11    CompactBad  528 B          压缩位图
12-15 DiffAddr    64 KiB         坏块替换表
16-18 OPRom       3 页           项目示例设备为全零
19-28 RDT         10 页          测试结果，来自 RDT_Result 前 160 KiB
29-100 Bank       72 页          工作固件 = core1 + core0
```

页边界由 ParamTable 里的 descriptor 决定：

```text
d4=4   Seed 起始
d5=5   Org 起始
d6=7   Erase 起始
d8=9   Total 起始
d9=11  Compact 起始
dA=12  Diff 起始
dB=16  OPRom 起始
dC=19  RDT 起始
dD=29  Bank 起始
dE=37  core1 结束 / core0 开始
```

这些值会回写到 `P+0x45`、`P+0x70..0x76`、`P+0xBE/0xBF`，固件启动时直接读它们。

## 2. Boot 三段

BootISP 文件 18432 字节，不是整块塞进去，而是按固定偏移切三段：

```text
文件 0x0000 起  →  页 0
文件 0x1800 起  →  页 3
文件 0x3000 起  →  页 2
```

顺序是 0、3、2，不是 0、1、2。这是原厂布局，不要"整理"成顺序。

另外，文件头部 `0x17E0..0x17EA` 有 10 字节会被改写（元数据），内容与固件
版本、跳转入口有关。本工具会照做，且与厂商镜像逐字节一致。

## 3. ParamTable（P）

1024 字节，是所有参数的汇总：颗粒几何、时序、容量、功能开关、坏块数、
descriptor 回填值。生成顺序：

```text
Flash.SET 行 + DriveSetting D
  → 参数派生（几何/ECC/容量）
  → SetChCeMap（拓扑）
  → BBT 回填 P+0x3E
  → DiffAddr / 容量回填
  → InfoBlock Calculate 回填 descriptor
```

**关键字段**（项目示例设备实测值）：

```text
P+0x1A = 06   页高字节，写错会导致第 64 页之后数据损坏
P+0x3E = 06   坏块行数
P+0x43 = 20h  每页 32 个扇区
P+0x45 = 1Dh  Bank 起始页（29）
P+0x76 = 25h  core1 结束页（37）
P+0xD0 = 07   Boot 初始化分支
P+0xD1 = 01
```

## 4. 坏块三类 + 压缩位图

```text
OrgBad     原始扫描，一分块一字节
EraseBad   擦除后新增，一分块一字节
TotalBad   两者合并，只取前 32 KiB
Compact    528 B 的压缩形式，前 512 B 是位图
```

四者不是冗余：固件会分别用于不同用途（坏块统计、替换分配、快速判断）。

## 5. OPRom 段与零填充

`OpRom.bin` 是 40448 字节（79 个扇区 → 3 页）。原厂镜像里这三页**内容是零**，
但 descriptor 仍然给它留了位置。工具必须同样处理：

```sh
--oprom-bytes 0x9E00      # 预留 40448 字节，内容全零
```

如果塞进真实的 OpRom 内容，布局不变、但内容不同；实测两种都能启动，本工具
选择与厂商一致的做法。

## 6. RDT 10 页

RDT（Read Disturb Test）结果。原厂流程中即使未执行 RDT，也会写入一段测试结果
（来自设备已有数据）。长度 10 页 = 163,840 B。

不启用 RDT 时这一步可以给 0 页，descriptor 会相应前移，但**必须整体自洽**。

## 7. Bank（工作固件）

```text
Bank = core1 (128 KiB) + core0_A3 (1 MiB) = 1,179,648 B = 72 页
```

`dD=29` 是起始页，`dE=37` 是 core1 结束/core0 开始的位置（8 页 = 128 KiB）。
core0 里 `file_length-0x10000` 处会被 working CID 覆盖 4096 字节。

## 8. typeMap

单独一份 101 字节的表，记录每页属于哪种类型（Boot/Param/Seed/Org/…/Bank）。
它在写系统块时作为 spare 的一部分，让固件知道"这一页该按什么格式解析"。

## 9. 段长度与总页数变化

```text
扫描到的坏块数  → Org/Erase/Total 的字节数（固定）
固件包大小      → Bank 页数
是否启用 OPRom  → 0 或 3 页
是否有 RDT 结果 → 0 或 10 页
```

所以不同盘、不同配置下 InfoBlock 可能是 101 页、104 页或别的值。判断标准不是
"页数等于多少"，而是 **descriptor 与实际内容一致、checksum 一致、能启动**。

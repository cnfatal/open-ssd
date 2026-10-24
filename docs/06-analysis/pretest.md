# Pretest：扫描、参数与坏块

## 1. 原厂 Pretest 执行阶段

```text
Step2 Do Pretest
  <1>  ReadRomVersion        读 ROM 版本
  <3>  ChkGPIOSetting        板级 IO 配置
  <4>  DumpSysBlock          读系统块
  <5>  CheckISPReadRDTResult 读 RDT 结果
  <6>  RefRTLastBad          参考上次坏块
  <7>  SramTest              主控 SRAM 自检
  <8>  FlashConnectivity     颗粒连通性检查
  <9>  SetChCeMap            通道/CE 映射
  <10> TranDriveSettingTable→ParamTable
  <11> SetCardMode           C1/90 下发
  <13> TranRTC               C2/8B，写 P+0x6C
  <15> TranAdj               时序调整
  <16> CheckRDTReport
  <18> ScanEraseBadBlock     C1/92 / C2/83
  <19> GenBadBlockBitMap     C1/91 / C2/85
  <20><23><27> CalBadBlockCnt
  <28> GenBadBlockBitMap
  <29> SetSystemBlockAndBoundaryBlock
  <30> GenDiffAddrTable
  <31> SetDiskCapacity
```

本工具将相关操作拆为独立子命令，支持分阶段执行与验证。

## 2. 连通性（第 8 步）

```sh
sudo ossd pretest connectivity --drive D.bin --out DIR --allow-probe
```

返回值是 4×4 的矩阵，每个非零格表示该 (CH（Channel，通道）, CE（Chip Enable，片选）) 上有 N 个 die：

```text
ch\ce   0     1     2     3
 0     0x03  0x00  0x03  0x00
 1     0x03  0x00  0x03  0x00
 2     0x03  0x00  0x03  0x00
 3     0x03  0x00  0x03  0x00
```

项目示例设备：4 通道 × CE0/CE2 × 2 die。**这一格数量和 Flash.SET 行必须一致**，
不匹配时可能导致连通性检查失败；项目原厂 10/21 的记录在该阶段报告失败。

## 3. 扫描描述符派生规则

原厂不是写死"扫 495 个块"，而是从参数算：

```text
T（总块数）   = 块数 / plane
R（每批块数） = 枚举值：默认 64
mode          = 1
pages[]       = 0, 2303, …（块内页采样）
offsets[]     = 4000h 起（页内偏移）
每批结果     = floor(R / 8) 个扇区
```

`PretestOption` 会改写它：

```text
PretestOption = 1  → R = 0（跳过 Org 扫描）
PretestOption = 0  → R = 64
PretestOption = 3  → R = 64，且擦除 mode 走另一支
```

**注意**：原厂包的默认配置是 `PretestOption=1`，该设置会跳过原始坏块扫描。
空片开卡要真扫，命令行里显式给 `--pretest-option 3`。

## 4. 原始坏块扫描（C1/91 → C2/85）

```sh
sudo ossd pretest scan-org --drive D.bin --pretest-option 3 \
  --result-dir DIR --allow-scan
```

- 分批提交，每批 `R` 个块；
- 每批后单独取结果；
- 结果按位打包，`floor(R/8)` 个扇区。

项目示例设备 8 批全部 `done=1 error=0`。重复 3 次：

```text
run0 17 行 / 62 bit
run1 18 行 / 66 bit
run2 16 行 / 58 bit
union 18 行 / 66 bit
```

边缘块（第 20、29 行）每次结果不同，所以默认取并集。

## 5. 擦除扫描（C1/92 → C2/83）

```sh
sudo ossd pretest erase-run --param P --drive D --bbt BBT --out DIR --allow-erase
```

```text
mode：PretestOption=1 → 0；否则 → 1
提交 C1/92（带 BBT 切片），再逐批 C2/83
不重试，第一个传输/状态失败就停
```

项目示例设备 8/8 批完成、0 个新增坏块。

## 6. 坏块位图与统计

```text
OrgBad      原始扫描结果，一个块一字节
EraseBad    擦除新增
TotalBad    合并（前 32 KiB 进 InfoBlock）
Compact     528 B 压缩位图（前 512 B 位图）
```

`bbt build --policy union|intersect|majority` 控制合并口径，默认 union。

扫描阶段的 P+3E 与最终容量使用的 P+3E 不同：DiffAddr 的 Check All Mapping
在 `41A23A..41A24F` 回填未恢复行数。必须先生成 DiffAddr，再计算容量。
旧 Python/C 注释中“DiffAddr 保留扫描计数”的说法被该写入点及历史 P fixture 推翻；
Python 已恢复回填，并恢复整个 P 的逐字节回归。

## 7. 系统块与容量

```text
layout system --fill     选 8 个未被标记的候选，写 P+20..27、P+30
layout capacity          算 data/reserve/surplus，写 P+0x2C/34/3A/60
```

项目示例设备结果：

```text
total=495  later_bad=6  system=1  static_slc=37
data=398   nominal=8177 reserve=53 surplus=46
sectors_per_fblock=4712448  total_sectors=1875385008
```

系统块候选可以用 `pretest probe-run` 逐个实测（擦+写 16 页+校验）；
项目示例设备 8/8 通过。

## 8. ParamTable 的关键字段

| 字段 | 含义 | 项目示例设备 |
| --- | --- | --- |
| `P+0x10..0x15` | CH/CE mask 与数量 | 0x0F / 0x05 / 4 / 2 |
| `P+0x1A` | 页高字节 = `D[248]>>5` | 6 |
| `P+0x3E` | DiffAddr 后未恢复的坏行数 | 6（历史样本） |
| `P+0x40..43` | 每页 sector 相关 | 40 80 10 20 |
| `P+0x45` / `0x76` | Bank 起止页 | 1D / 25 |
| `P+0xD0/0xD1` | Boot 初始化分支 | 07 / 01 |

`P+0x1A` 写错（=0）会让第 64 页之后的数据被污染，是历史上一处隐蔽 bug。

## 9. TranRTC

```sh
sudo ossd pretest tran-rtc --param P --out DIR --allow-probe
```

`C2/8B` 读 512 B，取首两字节 LE16，≤ `0x1FF` 时写 `P+0x6C/+0x6D`。
原厂本次得到 `0x0110`。它只被 `ChkProgTime` 消费，不影响启动。

## 10. 设备端参数使用规则

C1/90 之后，设备把 P 和 tail 落到固定 RAM（Random-Access Memory，随机存储器） 区；扫描命令按 P 里的
CH/CE 数量、plane 数、块数遍历。C2/83 只区分 `mode==0` 与非 0，
没有额外分支；系统块排除的间接来源仍未完全还原。

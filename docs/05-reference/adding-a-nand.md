# NAND 型号适配流程

以"同控制器、同桥、换 NAND（NOT AND，非与型闪存）"为前提。换主控不在本文范围。

## 0. 适配前提

```text
1. 新颗粒的 ID 能读出来                ossd read flash-id
2. 新颗粒的 ID 在 Flash.SET 里有对应行  没有就得先补表
3. 拓扑能读出来（几个 CE、每 CE 几个 die）  ossd pretest connectivity
```

第 3 步不能跳过：同一个 ID 可能有 4 CE（Chip Enable，片选） 和 8 CE 两种封装，仅凭 ID 无法区分。

## 1. Flash.SET 条目补充

如果表里没有，需要按 74 列格式新增一行。最少要确认：

```text
前 6 列  颗粒 ID
通道数、位宽
页大小（KB）、每页扇区
页/块、总块数
CE 数、die 数
时序/驱动相关列
```

这些值来自颗粒 datasheet 或原厂包。**参数需具有明确来源**：时序列不匹配时，Pretest 会在
连通性或训练阶段失败。

新增后使用工具验证解析结果：

```sh
ossd param build --set <Flash.SET 路径> --part "<新行名>" \
  --template $PKG/DriveSetting/DriveSettingTable_modify.bin \
  --matrix 03000300030003000300030003000300 --internal 2 \
  --ch-mask 0x0f --ce-mask 0x05 --out-dir work/new
```

核对输出的 `geometry:` 是否与 datasheet 一致，尤其是 `ce=`、`pages/block=`。

## 2. 新建颗粒描述

`docs/03-nand/<vendor>/<family>-<id>.json`：

```json
{
  "id": "ymtc:x2-9060:9bc5294920",
  "vendor": "ymtc",
  "flash_id": "9b c5 29 49 20 00",
  "cell": "TLC",
  "die_capacity_gibit": 512,
  "planes_per_die": 4,
  "die_per_ce": 2,
  "ce_total_observed": 8
}
```

## 3. 新建 profile

以 CE 数匹配的现有 profile 为基础，调整以下字段：

```text
match.nand            → 新颗粒 id
bind.flash_part_num   → Flash.SET 里的行名
bind.ce_total         → 实测 CE 数
```

`notes` 里记录第一次实机的结论（Pretest 结果、坏块数、容量），供后续故障排查与对照使用。

## 4. 固件选择

```text
BootISP  按 ROM 标签选（SVN02777 → A3）
core0    与 BootISP 修订配对（A3 ↔ core0_A3）
core1    通用
MPISP    通用
```

颗粒品牌变了但主控修订没变时，BootISP/core0 通常不用换；换的是 Flash.SET 行。

## 5. 适配验证

按以下顺序执行并记录各阶段结果：

```text
① param build            geometry 与 datasheet 一致
② connectivity           矩阵与预期 CE/die 一致
③ card-mode              P/tail 回读 match
④ scan-org               能完成，坏块数在合理范围
⑤ erase-run              完成，新增坏块为 0 或很少
⑥ layout capacity        data_fblocks > 0，容量合理
⑦ diffaddr               n1/n2 正常，Check All Mapping 通过
⑧ infoblock build        descriptor 单调递增，checksum 自洽
⑨ save-run + compare     host = device0 = device1
⑩ 冷启动                 容量、读写、二次冷启动
```

阶段失败时参阅 [排错](../02-controller/sm2263xt/opening/troubleshooting.md)。

## 6. 常见配置错误

| 配置错误 | 现象 | 处理 |
| --- | --- | --- |
| 用了同 ID 的另一种封装 | 只认出一半 CE | 按 `C2/80` 拓扑选择匹配行 |
| 沿用不匹配颗粒的时序列 | 连通性/训练失败 | 从原厂包或 datasheet 取 |
| 页大小写错 | 容量异常、写页错位 | 校验 `P43` |
| 坏块太多 | capacity 报错 | 确认扫描口径，必要时换盘 |
| 固件版本不匹配 | 写完不启动 | 同一包的 MPISP/ISP/CID |

## 7. 配置兼容性约束

```text
- 不要把 SM2263 的 opcode / 页布局套到其他控制器
- 不要用其他包的 BootISP 配这个包的 core0
- 不要为了让容量"看起来对"去改 P 里的块数
```

上述配置不一致可能导致介质访问或启动失败，应保留输入来源以便追溯。

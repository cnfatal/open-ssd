# C1/90（SetCardMode）：参数下发与读回

## 1. 命令用途与输入

把主机生成的参数表 P（1024 B）和尾部表（SeedTable，最大 4608 B）写进主控 RAM（Random-Access Memory，随机存储器），
让后续的扫描、擦除、写页用上正确的几何与时序。

```text
payload = P(1024B) + tail(4608B) + 补零到 512 的整数倍
N512    = payload / 512
CDW10   = N512 × 128
```

项目示例设备（2304 项 seed 表）：

```text
tail      = 4608 B = 0x1200
payload   = 5632 B = 0x1600
N512      = 11
CDW10     = 0x580
```

另一种 seed 表（1536 项）的 tail 是 3072 B，对应 N512=8、CDW10=0x400。
**选哪种取决于配置与颗粒，不能一律按 4608 处理。**

## 2. tail 的来源

```text
Tables/SeedTable2304.bin  4608 B = 2304 × 2B（每项 LE16）
Tables/SeedTable1536.bin  3072 B = 1536 × 2B
```

原厂逻辑（`ENSNINDICATOR=0/2` 且配置准备成功时）：先按 Page Number=2304
加载 2304 表，再生成每盘快照 → N512=11。其他分支可能先快照 1536 表。

**文件名里的 1536/2304 是表项数，不是字节数。** 表项数与字节数应分别解释。

## 3. 设备端 RAM 布局

```text
P          → RAM 参数区
tail       → 30100h..31300h（固定 4608 B 区域，长度 0x1200）
```

主机传入 3072 B 时，设备端保留区域仍为 4608 B，其余字节的来源尚未确认。
所以"读回 4608 B 全等于上传内容"只在主机确实给了 4608 B 时成立。

## 4. 读回：三条独立路径

| 命令 | 读什么 | 用途 |
| --- | --- | --- |
| `C2/87`（N512=2） | 1024 B DriveInfo，前 256 B 是 P | 校验参数是否落地 |
| `C2/52`（N512=9） | 地址 0x30100 起 4608 B | 校验 tail |
| `C2/88`（512 B） | 上一条命令的状态块 `VNDRCMDBGINFO` | 判断完成/错误 |

状态块的判读：

```text
+0x11 = done
+0x12 = error
+0x13 = 上一条命令 CDW12 的低字节（不是 opcode 本身）
+0x20 = CDW12..15 回显
```

**`C2/88` 的 `+0x13` 只是回显，不代表配置正确。** 早期曾用"错误拓扑"和
"正确拓扑"分别执行一次，`C2/88` 内容完全相同——所以它不能作为配置正确性的判据，
必须比对 `C2/87` 的 P 与 `C2/52` 的 tail。

## 5. 实测校验顺序

```sh
sudo ossd pretest card-mode --param P.bin --drive D.bin \
  --out DIR --allow-param-load
```

工具会依次打印：

```text
readback P[0:256]: match
readback tail[0:4608]: match
readback 0x30000 P[0:256]: match, tail[0:256]: match
readback CH map prefix: 0 1 2 3; CE map prefix: 0 2: consistent
readback bank pointers: 51100000 51100000 51100000 (expected 51100000): match
```

最后一行是 RAM 里的 bank 指针，`51100000` 表示三个窗口都指向 bank 8。

## 6. padding 与覆盖顺序

- 主机缓冲区必须是"已完整初始化"的，未用部分补零，不得保留未初始化内容；
- 长度按实际文件读取长度算，不是固定 5632；
- P 本身在生成过程中会被写多次（拓扑、坏块数、descriptor），
  **下发前必须是最终版本**。

## 7. 常见错误

| 现象 | 原因 |
| --- | --- |
| `readback P mismatch` | P 不是最终版，或 CH（Channel，通道）/CE（Chip Enable，片选） 映射错 |
| `readback tail mismatch` | 用了 1536 表但按 4608 下发（或相反） |
| 命令被接受但扫描失败 | P 里的几何/时序与实际颗粒不符 |
| 后续写页错位 | `P+0x43`（每页扇区）错 |

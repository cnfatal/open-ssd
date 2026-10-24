# 协议交互参考

本工具和主控之间只有两层协议：**USB（Universal Serial Bus，通用串行总线） BOT（Bulk-Only Transport，USB 批量传输协议） 上的 A1 厂商透传** + **64 字节 SQE（Submission Queue Entry，提交队列项）**。
本文按命令列出请求字段、数据布局与完成条件。

## 1. 传输层

```text
主机 ── BOT(CBW/DATA/CSW) ── JMS583 ── A1 厂商透传 ── 主控
```

A1 的四个子操作：

| 子命令 | 用途 | 数据方向 |
| --- | --- | --- |
| `A1/80` | 准备一条命令 | 无 |
| `A1/83` | 带 payload 发送 | OUT |
| `A1/81` | 执行（无数据） | 无 |
| `A1/8F` | 取完成状态 | 无 |

返回数据用普通 SCSI 读回。CSW（Command Status Wrapper，命令状态封装） 的 residue 在写方向可能报"全长未传"但
NVMe（Non-Volatile Memory Express，非易失性存储接口规范） 状态为 0，工具按桥的默认策略放行（见
[../04-bridge/jms583.md](../../04-bridge/jms583.md)）。

## 2. SQE 布局

```text
偏移  字段      含义
0     opcode    C0 / C1 / C2
40    CDW10     数据长度：N512 × 128（= 字节数 / 4）
48    CDW12     子命令 + 模式 + 标志
52    CDW13     地址/页块/批次
56    CDW14     物理地址或扩展参数
60    CDW15     部分命令使用（如 checksum 的 extra）
```

长度换算：

```text
N512 = 字节数 / 512
CDW10 = N512 × 128
```

例：2048 B → N512=4 → CDW10=0x200；4608 B → N512=9 → CDW10=0x480。

## 3. 命令总表

| 命令 | 名称 | 方向 | 长度 | 用途 |
| --- | --- | --- | --- | --- |
| `C2/40` | Read Flash ID | IN | 2048 | 颗粒 ID |
| `C2/4E` | Physical Read | IN | (P43+1)×512 | 读物理页 |
| `C1/83` | Physical Write | OUT | (P43+1)×512 | 写物理页 |
| `C0/03` | Erase Block | 无 | — | 擦块 |
| `C0/01` | Reset | 无 | — | 主控复位 |
| `C1/80` | Upload | OUT | ≤16 KiB/包 | 上传 MPISP |
| `C1/90` | SetCardMode | OUT | 5632 | 下发 P + tail |
| `C1/91` | Org Scan Submit | 无 | — | 提交原始坏块扫描 |
| `C2/85` | Org Scan Result | IN | R/8 扇区 | 取扫描结果 |
| `C1/92` | Erase Scan Submit | OUT | 512 | 提交擦除扫描 |
| `C2/83` | Erase Scan Result | IN | 1 | 取擦除结果 |
| `C2/80` | Connectivity | IN | 1024 | 拓扑矩阵 |
| `C2/87` | Read DriveInfo | IN | 1024 | 参数/模式 |
| `C2/52` | Read RAM（Random-Access Memory，随机存储器） | IN | 任意 | 读 RAM（tail 等） |
| `C2/88` | Debug Info | IN | 512 | 上一条命令的状态 |
| `C2/8B` | RTC | IN | 512 | 校准值 → `P+0x6C` |
| `C2/8A` | RDT Read | IN | 页 | 读 RDT 页 |
| `C2/8D82` | Checksum | IN | 4 | 区域累加校验 |

## 4. 逐条帧

### C2/40 读颗粒 ID

```text
CDW10 = 0x200 (2048B)   CDW12 = 0x40   CDW13 = selector(0)
```

响应前 0x30 起是 bank 记录，每条 8 字节：
`ID0 ID1 ID2 ID3 ID4 ID5 00 00`。

### C1/90 SetCardMode

```text
CDW10 = 0x580 (N512=11, 5632B)
CDW12 = 0x90
payload = P(1024) + tail(4608)
```

设备把 tail 放到 `0x30100..0x31300`。

### C2/87 读参数

```text
CDW10 = 0x100 (N512=2, 1024B)
CDW12 = 0x87
```

前 256 B 是 P。`+0x210` 是运行模式类型，`+0x211` 起是模式前缀。

### C2/52 读 RAM

```text
CDW10 = N512×128
CDW12 = 0x52
CDW13 = 目标地址
```

tail 读回：`CDW13=0x30100`，`N512=9`（4608 B）。

### C2/4E 读物理页

```text
CDW10  = (P43+1)×128      例：33×128 = 0x1080
CDW12  = mode<<8 | 0x4E | (plane>>7)<<16
CDW13  = page<<16 | block
CDW14  = die<<24 | read_byte34<<16 | plane<<8 | ch | ce<<4
```

### C1/83 写物理页

```text
CDW10 = (P43+1)×128
CDW12 = mode<<8 | 0x83 | (plane>>7)<<16
CDW13 = page<<16 | block
CDW14 = die<<24 | plane<<8 | ch | ce<<4
```

Save 时 `mode` 前 4 页 `0x95`、其余 `0xC5`；MPInfo 用 `0xC5`。

### C0/03 擦块

```text
CDW10 = 0
CDW12 = mode<<8 | 0x03 | (plane>>7)<<16
CDW13 = block
CDW14 = die<<24 | plane<<8 | ch | ce<<4
```

Save 擦除 `mode=0x84`。

### C0/01 复位

```text
CDW10 = 0   CDW12 = 0x01   CDW13 = 0
```

没有 CSW 是正常的（设备直接重启）。

### C1/80 上传 MPISP

6 包：5×16 KiB + 1×9 KiB。

```text
CDW10 = 包字节数 / 4
CDW12 = 0x80000088（分块包）/ 0x88（单包）
CDW13 = 起始扇区 | (最后一包 ? 0x80000000 : 0)
```

### C1/91 → C2/85 原始坏块扫描

提交（无 payload）：

```text
C1/91  CDW12 = 0x91
```

取结果：

```text
C2/85  CDW12 = 0x85
N512 = floor(R/8)          R=64 → 8 扇区 = 4 KiB
```

扫描参数（T、R、mode、pages、offsets、batch）在提交前通过另一条描述符
写入，工具里是 512 B 的 descriptor 结构：

```text
+0  first(LE16)   +2 last(LE16)   +4 mode   +5..7 三个字节配置
+8  5 × pages(LE16)   +18 7 × offsets(LE16)   +32 blocks_per_batch
```

### C1/92 → C2/83 擦除扫描

提交（512 B，带 BBT（Bad Block Table，坏块表） 切片）：

```text
C1/92  CDW12 = 0x92
```

取结果：

```text
C2/83  CDW10 = 128 (512B)
       CDW12 = mode<<8 | 0x83
       CDW13 = last<<16 | first
       CDW14 = blocks_per_batch
```

### C2/80 连通性

```text
CDW10 = 0x200 (1024B)
CDW12 = 0x80
CDW13 = internal_chip_number | log2(die_address) + table[FlashInterface>>5] << 8
```

响应是 4×4 矩阵，非零格表示该 (CH（Channel，通道）,CE（Chip Enable，片选）) 上有几个 die。

### C2/88 状态块

```text
CDW10 = 0x80 (512B)   CDW12 = 0x88
```

响应头 `VNDRCMDBGINFO`：

```text
+0x11 = done
+0x12 = error
+0x13 = 上一条命令 CDW12 的低字节
+0x20 = 上一条命令 CDW12..15 的回显
```

**它只回显，不判断对错**；配置是否正确要靠 `C2/87`/`C2/52` 的内容比对。

### C2/8B RTC

```text
CDW10 = 0x80 (512B)   CDW12 = 0x8B
```

取响应前两字节 LE16，≤ `0x1FF` 时写入 `P+0x6C/+0x6D`。

### C2/8D82 Checksum

```text
CDW10 = 0x80 (4B 够用)
CDW12 = 0x8D82
CDW13 = count<<16 | block
CDW14 = die<<24 | plane<<8 | ch | ce<<4
CDW15 = extra
```

响应前 4 字节按 LE32 解释，与主机 sum32 比较。

## 5. 典型序列

### 开卡主链

```text
C2/40 读 ID
C1/80 ×6 上传 MPISP
C2/87 确认 mode=MPISP
C1/90 下发 P+tail
C2/87 + C2/52 + C2/88 回读校验
C1/91 / C2/85 ×8   原始坏块扫描
C1/92 / C2/83 ×8   擦除扫描
（离线生成 InfoBlock / MPInfo）
C0/03 ×3 + C1/83 ×1537  写 InfoBlock（两份副本 + Idx）
C2/8D82 比较
C0/03 + C1/83 ×768     写 MPInfo
C2/8D82 比较
C0/01 复位
```

### 读一页

```text
C2/4E  →  IN (P43+1)×512
C2/88  →  状态
```

### 写一页

```text
C1/83  →  OUT (P43+1)×512
C2/88  →  状态
```

## 6. 完成判定

```text
1. BOT 层：CSW 状态字节
2. NVMe 层：CQ entry 的 status（不能只看 SCT/SC 的某几位）
3. 命令层：
   - 扫描类看 C2/88 的 +11(done) / +12(error)
   - 写页/擦除后必须单独读一次 C2/88
   - 校验类看 C2/8D82 返回的 4 字节
```

常见扫描错误码：

```text
0xE0  超时
0xFE  地址越界
0xFF  地址错误
```

## 7. 编码约定与注意事项

```text
地址：   die<<24 | plane<<8 | ch | ce<<4      （读写页额外带 read_byte34）
页块：   page<<16 | block
plane 高位： plane>>7 放进 CDW12 bit16（只用 7 位时）
```

- `C2/88` 的 `+0x13` 是 **CDW12 低字节**，不是 opcode；早期按 opcode 比较
  导致误判。
- `C2/8D82` 的 count 是页数，不是字节数。
- Save 的擦除模式和写页模式不同（0x84 vs 0x95/0xC5），不能互相套用。

## 8. 报文样例

SQE 由本仓库的构帧器生成（`ossd/generator/physical.py`），**与实际上线字节相同**；
响应来自项目示例设备的实际命令返回。

下表只列 `[0]` 与 `[40..64)`（`CDW10..CDW15`），中间 39 字节为 0。

### C2/40 读颗粒 ID

```text
请求  c2  00 02 00 00 | 00 00 00 00 | 40 00 00 00 | 00 00 00 00 | 00 00 00 00
      op  CDW10=0x200           CDW12=0x40
响应  9b c5 29 49 20 00 00 00  9b c5 29 49 20 00 00 00
      （8 个 bank 记录，从 +0x30 起，每个 8 字节）
文件  connectivity-2026-10-22/connectivity-ids.bin
```

### C2/80 连通性

```text
请求  c2  00 01 00 00 | 00 00 00 00 | 80 00 00 00 | 02 07 00 00 | 00 00 00 00
                                  CDW12=0x80   CDW13=0x0702
响应  03 00 03 00 03 00 03 00  03 00 03 00 03 00 03 00
      4×4 矩阵：每格 0x03 = 2 die；非零位置为 CE0/CE2
文件  connectivity-2026-10-22/connectivity-matrix.bin
```

### C1/90 下发参数

```text
请求  c1  80 05 00 00 | 00 00 00 00 | 90 00 00 00 | 00 00 00 00 | 00 00 00 00
      op  CDW10=0x580 (5632B)  CDW12=0x90
payload  P(1024) + tail(4608)
```

### C2/87 读 DriveInfo

```text
请求  c2  00 01 00 00 | 00 00 00 00 | 87 00 00 00 | 00 00 00 00 | 00 00 00 00
      op  CDW10=0x100 (1024B)  CDW12=0x87
响应  53 4d 32 32 36 33 50 41 52 41 9b 07 f2 3f 00 00
      "SM2263PARA" + P[0:6]；+0x210 是模式类型
```

### C2/52 读 RAM（tail）

```text
请求  c2  80 04 00 00 | 00 00 00 00 | 52 00 00 00 | 00 01 03 00 | 00 00 00 00
      op  CDW10=0x480 (4608B)  CDW12=0x52  CDW13=0x30100
响应  4608 B，逐字节等于下发的 tail
```

### C2/88 状态块

```text
请求  c2  80 00 00 00 | 00 00 00 00 | 88 00 00 00 | 00 00 00 00 | 00 00 00 00
      op  CDW10=0x80 (512B)    CDW12=0x88
响应  56 4e 44 52 43 4d 44 42 47 49 4e 46 4f 00 00 00   "VNDRCMDBGINFO"
      01 01 00 90 ...
      +0x10=01  +0x11=done=1  +0x12=error=0  +0x13=0x90（上一条是 C1/90）
文件  card-mode-2026-10-22/status-v2.bin
```

### C1/91 → C2/85 原始坏块扫描

```text
提交  c1  80 00 00 00 | 00 00 00 00 | 91 00 00 00 | 00 00 00 00 | 00 00 00 00
取结果 c2 00 04 00 00 | 00 00 00 00 | 85 00 00 00 | 00 00 00 00 | 00 00 00 00
      CDW10=0x400 (8 扇区 = 4 KiB，R=64 → floor(64/8)=8)
```

### C1/92 → C2/83 擦除扫描

```text
提交  c1  80 00 00 00 | 00 00 00 00 | 92 00 00 00 | 00 00 00 00 | 00 00 00 00
取结果 c2 80 00 00 00 | 00 00 00 00 | 83 00 00 00 | 00 00 ef 01 | 01 00 00 00
      CDW13 = last<<16|first = 0x01EF0000（last=495）
      CDW14 = blocks_per_batch = 1
```

### C2/4E 读物理页

```text
请求  c2  80 10 00 00 | 00 00 00 00 | 4e 9d 00 00 | 00 00 00 00 | 00 00 00 00
      CDW10=0x1080 (33×512)  CDW12=0x9D4E（mode=0x9D, sub=0x4E）
响应  53 4d 32 32 36 33 41 41 42 54 41 4f 00 00 18 40   "SM2263AABTAO…"
```

### C1/83 写物理页

```text
请求  c1  80 10 00 00 | 00 00 00 00 | 83 95 00 00 | 00 00 00 00 | 00 00 00 00
      CDW10=0x1080  CDW12=0x9583（mode=0x95，前 4 页）
payload  16384 B 主数据 + 512 B spare
```

### C0/03 擦块

```text
请求  c0  00 00 00 00 | 00 00 00 00 | 03 84 00 00 | 00 00 00 00 | 00 00 00 00
      CDW12=0x8403（mode=0x84，sub=0x03）
```

### C2/8D82 校验

```text
请求  c2  80 00 00 00 | 00 00 00 00 | 82 8d 00 00 | 00 00 68 00 | 00 00 00 00
      CDW13 = count<<16|block = 104<<16
响应  33 be 05 06  →  LE32 = 0x0605BE33
```

### C0/01 复位

```text
请求  c0  00 00 00 00 | 00 00 00 00 | 01 00 00 00 | 00 00 00 00 | 00 00 00 00
响应  无 CSW（设备直接重启）
```

## 9. 实现约束（契约）

以下是实现一个兼容客户端时必须遵守的规则，不只是建议。

### 9.1 分层职责

| 层 | 负责 | 不应承担 |
| --- | --- | --- |
| 板与供电 | 实物版本、启动脚、电压 | 从 USB 型号推断 NAND（NOT AND，非与型闪存） |
| OS 后端 | 打开目标、接口所有权、超时、释放 | 选择颗粒或固件 |
| 桥协议 | 逻辑命令 ↔ CDB/阶段 | 把一个桥的封装推广到其他桥 |
| 控制器协议 | 厂商命令、运行模式、状态轮询 | 假定所有维护模式能力相同 |
| 量产流程 | 阶段前置、分支、持久化、验证 | 用退出码或进度条判断完成 |

### 9.2 阶段记录

每个阶段至少记录：

```text
stage_id               阶段名
inputs                 输入结构及版本
state_before           进入前的目标状态与依据
operations             实际发送的命令序列
guard                  允许执行的前置条件
postconditions         判定完成的条件
failure_edges          失败分支
timeout                数值 + 单位 + 来源
retry_policy           能否重试、重试是否安全
effects                RAM / 模式 / 持久化
```

**写操作之后超时或复位失败，状态必须是"未知，需要重新识别"**，不能自动回到起点重放
写操作——可能已经写入了。

### 9.3 命令记录字段

```text
operation_id      语义名（不是裸 opcode）
target_state      执行前后目标处于什么模式
data_direction    none / host→device / device→host
effects           host-only / device-read / RAM-write / mode-change / persistent-write
payload           长度、对齐、字节序、计数单位、标志位
expected_reply    magic、版本、边界、校验、后续轮询
timeout / retry   单位与来源；未知就不要设"通用重试"
evidence          构造代码、调用者、返回处理、验证等级
```

### 9.4 四层状态分别保留

```text
1. 系统调用/OS 返回值
2. USB / BOT：CSW 状态、residue
3. SCSI sense / 桥签名
4. NVMe completion：原始 16 字节 + result + SC/SCT
```

不要只保留"成功/失败"一个布尔。桥可能报 residue 异常但 NVMe 状态为 0，
也可能 NVMe 返回非零而桥报成功。

### 9.5 地址与长度的写法

```text
address_kind     file_offset / pe_rva / pe_va / host_buffer / controller_address
                 / nand_page / nand_block —— 每个地址都要标清是哪一种
PE 映射          RVA = VA - ImageBase
                 file_off = PointerToRawData + RVA - VirtualAddress
                 必须校验落在 raw data 范围内（BSS 区没有文件字节）
长度             必须带单位：bytes / DWORD / N512 / 枚举值
                 注明是否含头、是否补零、尾包如何处理
```

### 9.6 未确定字段的表示规则

```text
unknown          没有证据
not_inspected    没检查
not_applicable   不适用
```

这三者都不能被悄悄替换成 0、默认电压或"兼容模式"。把未知写成 0 会让
失败看起来像成功（本项目就踩过 `P+0x1A=0` 导致第 64 页后数据损坏）。

### 9.7 验证等级

```text
device_verified   本机实测
static_verified   原件指令/字节级还原
mock_verified     隔离模型验证
reference_only    仅外部资料
inferred          推断
unknown           未知
```

一个参数来自官方文档，不等于它在设备上被验证过。

### 9.8 序列化

逐字段处理字节序与范围；不依赖 C 结构体 packing、位域布局或未对齐访问；
不把主机指针/PE 地址当作主控地址写进设备字段。

## 10. 未解边界

```text
- C1/80 末包 bit31 的设备端语义（是否触发执行）
- C2/83 mode 在设备内部的完整分支
- 系统块排除的间接来源
- RDT 相关命令在正常开卡中是否必需
```

这些不影响当前流程，但换固件版本时需要重新核对。

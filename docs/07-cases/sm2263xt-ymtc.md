# SM2263XT + YMTC：开卡与原生 PCIe 验证

本案例记录一块 SM2263XT AD SSD 从工厂模式到正常枚举的配置、排查和验证过程。
原厂 MPTool 已完成开卡，Windows USB 连接与 Linux M.2 直连均已识别。
Python 实现按该设备的输入和输出进行对照，当前验证进度列于第 6 节。

## 1. 硬件与固件

| 项目 | 配置 |
| --- | --- |
| 主控 | 慧荣 SM2263XT AD |
| ROM 标签 | `2263ROM:SVN02777` |
| NAND 封装 | 两个，表面丝印记录为 `KRN09TC1B1JD2C` |
| Flash ID | `9B C5 29 49 20 00` |
| 连接拓扑 | 4 通道，每通道 CE0、CE2 有效，每个有效片选位置 2 die，共 16 die |
| 开卡连接 | JMS583 USB–NVMe 桥 |
| 原厂包 | `SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A` |
| 运行固件版本 | `V0126A0` |

CE（Chip Enable）表示片选，die 表示晶粒。封装丝印与参数库行名来自不同来源，不能直接互换。

## 2. 配置选择

同一个 Flash ID 在参数库中对应多个拓扑，需结合连通性矩阵选择。
本设备的 8 个有效片选位置、每位置 2 die 对应 Flash.SET 的 A2 行：

```ini
FlashPartNum=YMTC,8Tbit,YMN09TC1B1OC6C(TAS)(2Die)(SM2263XT)
```

原包 `Config/YMTC_TAS_ISP_2DIE.ini` 默认指向 2Tbit 的 A0 行，与该设备不匹配。
早期原厂记录在 `FlashConnectivity` 阶段失败；改为匹配的 A2 配置后完成 Pretest 和 ISP 下载。

| 输入 | 选定内容 | 依据 |
| --- | --- | --- |
| NAND 参数 | Flash.SET A2，8 CE × 2 die | Flash ID 与连接拓扑 |
| DriveSetting | `DriveSettingTable_modify.bin` 基底 | 原厂成功记录的配置覆盖位，D00=0x90 |
| BootISP | `BootISP2263A3.bin` | ROM 标签 `SVN02777` |
| 工作固件 | `ISP2263XT_core0_A3.bin` + `ISP2263XT_core1.bin` | 与主控修订匹配 |
| SeedTable | `SeedTable2304.bin`，4608 B | 对应块内 2304 页配置 |

Flash.SET 的 **A2 是 NAND 配置别名**，BootISP/core0 的 **A3 是主控固件修订**，两者独立选择。

## 3. 开卡过程

```text
P13 工厂短接后上电，进入 ROM
  → 加载 MPISP 维护程序
  → 检查 NAND 拓扑并下发参数
  → Pretest、坏块处理与容量计算
  → 生成并写入 InfoBlock，比较两个副本
  → 写入 MPInfo
  → 复位
  → 完整断电、解除 P13 短接、重新上电
  → 查询身份、容量并验证读取
```

首次成功记录的日志仍包含：

```text
Pretest Pass
DL_ISP Pass
CheckISP Fail
Result 611E(0100)
```

当时工厂短接仍接通。解除短接并完整断电重启后，设备正常枚举。
该次 `CheckISP Fail` 不能作为开卡失败的最终判断，需要结合正常启动条件下的结果。

逐阶段命令与输入见 [开卡流程](../02-controller/sm2263xt/opening/card-opening-guide.md)。

## 4. 开卡结果

2026-10-23，Windows 通过 USB 桥识别结果：

| 项目 | 结果 |
| --- | --- |
| 容量 | 960,197,124,096 B |
| 逻辑块 | 1,875,385,008 个，每个 512 B |
| 分区状态 | RAW，未分区 |
| 健康状态 | Healthy / Online |
| 读取测试 | 原始读取 512 B 成功 |
| 冷启动 | 解除短接后可重复枚举 |

开卡后的原厂导出包括参数表、DriveSetting、SeedTable、ISP 包和 MPInfo。
这些产物用于对照 Python 的参数派生与镜像生成规则。

## 5. Linux 原生 M.2 验证

后续使用原厂再次开卡的设备安装到 ASUS PRIME X399-A 的 M2.2 插槽。
最初在主机运行中插入，没有枚举到 NVMe 设备；重启主机后识别成功。
此次 Linux 验证为软件重启后的结果，没有执行主机物理断电。

2026-10-24 的结果如下：

| 项目 | 结果 |
| --- | --- |
| PCIe 设备 | `0000:41:00.0`，`126f:2263` |
| 驱动与节点 | nvme，`/dev/nvme0n1` |
| 链路 | 端点与上游端口均为 8 GT/s ×4，即 PCIe Gen3 ×4 |
| 型号 / 固件 | `SMI2263XT` / `V0126A0` |
| 容量 | 960,197,124,096 B |
| 读取测试 | 开头、中间、末尾各 1 MiB，直接读取成功 |
| SMART | Critical Warning、Media Errors、Error Log Entries 均为 0 |

该轮没有写入、格式化或执行测速。内核仍报告 SUBNQN 与 namespace 标识警告，未阻止驱动绑定和读取。
单次成功结果不代表所有启动条件下均无间歇性问题。

## 6. Python 实现对照与修正

| 项目 | 已确认结果 |
| --- | --- |
| BootISP / SeedTable | 对应样本与原厂产物逐字节一致 |
| 工作固件包 | 已对齐组包规则，早期差异集中于 CID 身份字段 |
| MPInfo 身份字段 | 修复 +0x1280..0x128B 缺少六个 PCI/NVMe ID 副本的问题 |
| MPInfo 配置快照 | +0x1400 使用 DriveSetting 前 1024 B |
| 离线对照 | 修正后原指令数据流产生预期 PCI/NVMe 标识 |
| 修正版原生 M.2 验收 | 尚未重新刷写修正版完成硬件验证 |

旧 Python 产物缺失的 ID 副本会使对应固件路径产生零 PCI/NVMe 标识。
这个数据缺陷不能笼统归为链路训练失败，也不能仅由 USB 桥下可见设备推断原生 PCIe 正常。
字段与数据流见 [MPInfo 分析](../06-analysis/mpinfo.md)。

本案例中的原厂开卡成功结果，为自研流程提供输入、产物和硬件验收基准。
其他 NAND 或主控修订需重新匹配参数和固件，不能直接套用 A2/A3 选择。

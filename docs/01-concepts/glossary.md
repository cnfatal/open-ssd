# 术语表

本文定义 SSD 初始化涉及的通用术语。SM2263XT 专用名称、字段和长度在表中单独标明，其他主控的实现可能不同。

## 1. 闪存物理结构

| 术语 | 英文 | 解释 |
| --- | --- | --- |
| 颗粒 / 芯片 | NAND package | 焊接在板上的闪存封装，一个封装可包含多个 die |
| 晶粒 | die | 能独立执行读写的最小单元；一颗 die 有多个 plane |
| 平面 | plane | die 内部并行单元，同一 die 的两个 plane 可并行操作 |
| 块 | block | 擦除的最小单位；写之前必须先擦 |
| 页 | page | 常见的读取和编程单位，大小及部分页操作限制由 NAND 决定 |
| 扇区 | sector | 主机侧逻辑块单位，常见大小为 512 B 或 4 KiB；以 namespace 格式为准 |
| 备用区 | Out-of-Band（OOB）/ spare | 每页主数据之外的附加字节，用于 ECC、坏块标记等 |
| 通道 | Channel（CH） | 主控到 NAND 的总线，多通道可并行 |
| 片选 | Chip Enable（CE） | 选择 NAND 目标的接口信号，与 die 数量不一定一一对应 |
| 逻辑单元号 | Logical Unit Number（LUN） | 可独立寻址的逻辑单元，一个 CE 可以访问多个 LUN，具体关系取决于 NAND |

SM2263XT 示例拓扑：4 个通道 × 每通道 2 个有效 CE 位置 × 每个位置 2 个 die = 16 die。该关系来自示例配置，不由封装数量直接推算。

## 2. 主控与运行状态（含 SM2263XT 名称）

| 术语 | 解释 |
| --- | --- |
| 主控 | 固态硬盘的控制器，包含处理器和介质接口，执行 FTL、ECC 与 NAND 时序控制 |
| ROM / BootROM | 主控片内固化的启动代码，负责早期初始化及程序加载 |
| MPISP | 主机上传至 SRAM 的维护程序，执行介质配置、测试和系统区写入 |
| ISP | 工作固件，从 NAND 加载，负责对外提供 NVMe |
| BootISP | 复位后由 ROM 从 NAND 读出并执行的第一段固件 |
| P13 | SM2263XT 示例板的工厂模式选择点；短接拉低进入 ROM，解除后按正常启动路径启动 |
| 短接 | 连接板上的测试点；此项目示例指拉低 P13 进入 ROM，其他板卡需按设计确认 |

## 3. 开卡与系统数据（长度为 SM2263XT 示例格式）

| 术语 | 英文 | 解释 |
| --- | --- | --- |
| 开卡 | initialization / MP | 用工具把空片变成可用 SSD 的全过程 |
| 量产工具 | MPTool | 厂商提供的开卡上位机程序 |
| InfoBlock | 系统信息块 | 存在 NAND 系统块里的元数据集合，含固件、参数、坏块表 |
| ParamTable (P) | 参数表 | 1024 B，告诉主控颗粒几何、时序、容量、功能 |
| DriveSetting (D) | 驱动设置 | 2048 B，参数表的输入之一，含颗粒列和功能位 |
| MPInfo | 量产信息 | 8 KiB，含 CID、身份字段、统计及 DriveSetting 片段等量产信息 |
| CID | Controller ID / LightSwitch | 4 KiB 的控制器身份与配置块 |
| OOB / spare | 页备用区 | 每个 NAND 页的附加区域，与 OP 预留容量不同 |
| BBT | Bad Block Table | 坏块位图 |
| DiffAddr | 差异地址表 | 坏块到替换块的映射表 |
| FBlock | Firmware Block | 主控视角的"逻辑块"，由多个物理块拼成 |
| typeMap | 页类型表 | 记录 InfoBlock 每一页装的是什么 |
| RDT | 厂商可靠性测试 | 测试内容由配置决定，会产生结果数据 |
| OP | Over-Provisioning | 预留空间，用于坏块替换和 GC |

## 4. 传输与协议

| 术语 | 解释 |
| --- | --- |
| BOT | Bulk-Only Transport，USB 批量传输协议 |
| CBW | Command Block Wrapper，BOT 的命令块封装 |
| CSW | Command Status Wrapper，BOT 的命令状态封装 |
| residue | CSW 里"没传完的字节数"字段 |
| 透传 | passthrough，把一条完整命令原样发给设备 |
| SQE | Submission Queue Entry，提交队列项；NVMe 命令描述为 64 B |
| CDW10/12/13 | SQE 里三个通用参数字段 |
| namespace | NVMe 的"逻辑盘"，一个主控可以暴露多个 |
| LBA | Logical Block Address，逻辑块地址 |

## 5. 项目实现中的缩写

| 缩写 | 含义 |
| --- | --- |
| `ossd` | 本工具的 CLI 名 |
| SET | `Flash.SET`，颗粒参数数据库 |
| LS | LightSwitch，即 CID |
| P / D | ParamTable / DriveSetting |
| PD0 | P 的 `+0xD0` 字节，Boot 用它决定初始化分支 |

## 6. 常用缩写全称

| 缩写 | 英文全称 | 中文含义 |
| --- | --- | --- |
| SSD | Solid-State Drive | 固态硬盘 |
| NAND | NOT AND | 非与型闪存 |
| USB | Universal Serial Bus | 通用串行总线 |
| PCIe | Peripheral Component Interconnect Express | 高速串行扩展总线 |
| NVMe | Non-Volatile Memory Express | 非易失性存储接口规范 |
| CPU | Central Processing Unit | 中央处理器 |
| SRAM | Static Random-Access Memory | 静态随机存储器 |
| RAM | Random-Access Memory | 随机存储器 |
| ROM | Read-Only Memory | 只读存储器 |
| FTL | Flash Translation Layer | 闪存转换层 |
| ECC | Error Correction Code | 纠错码 |
| OOB | Out-of-Band | 页备用区 |
| GC | Garbage Collection | 垃圾回收 |
| OP | Over-Provisioning | 预留空间 |
| CE | Chip Enable | 片选 |
| CH | Channel | 通道 |
| LUN | Logical Unit Number | 逻辑单元号 |
| LBA | Logical Block Address | 逻辑块地址 |
| BBT | Bad Block Table | 坏块表 |
| BOT | Bulk-Only Transport | USB 批量传输协议 |
| CBW | Command Block Wrapper | 命令块封装 |
| CSW | Command Status Wrapper | 命令状态封装 |
| SQE | Submission Queue Entry | 提交队列项 |
| GPIO | General-Purpose Input/Output | 通用输入输出 |
| CLI | Command-Line Interface | 命令行接口 |
| GUI | Graphical User Interface | 图形用户界面 |
| TLC | Triple-Level Cell | 每单元存储 3 bit |
| SLC | Single-Level Cell | 每单元存储 1 bit |
| LDPC | Low-Density Parity-Check | 低密度奇偶校验码 |
| NQN | NVMe Qualified Name | NVMe 限定名称 |
| ASPM | Active State Power Management | 活动状态电源管理 |
| HMB | Host Memory Buffer | 主机内存缓冲 |
| VID | Vendor ID | 厂商标识 |
| SSVID | Subsystem Vendor ID | 子系统厂商标识 |
| DID | Device ID | 设备标识 |
| GND | Ground | 地 |
| SCSI | Small Computer System Interface | 小型计算机系统接口及命令体系 |
| CDB | Command Descriptor Block | SCSI 命令描述块 |
| ID | Identifier | 标识符 |
| SN | Serial Number | 序列号 |
| ONFI | Open NAND Flash Interface | 开放 NAND 闪存接口 |
| OUI | Organizationally Unique Identifier | 组织唯一标识符 |
| EUI-64 | 64-bit Extended Unique Identifier | 64 位扩展唯一标识符 |

## 7. 厂商程序与字段名称

MPISP、ISP、BootISP、CID、RDT、DiffAddr 和 FBlock 在本文档中按厂商工具或项目实现中的名称使用。其具体含义和布局以对应主控文档为准，不将推测的英文展开作为协议依据。

- **MPISP**：量产维护程序；**ISP**：工作固件；**BootISP**：引导程序。
- **CID / LightSwitch**：控制器身份与配置块；**MPInfo**：量产信息块。
- **RDT**：厂商可靠性测试及结果数据的名称，具体测试项目由配置决定。
- **P / ParamTable**：参数表；**D / DriveSetting**：驱动设置表。
- **DiffAddr**：替换地址表；**FBlock**：固件块组织单位。
- **CDWn**：Command Dword n，命令的第 n 个 32 位字；例如 CDW10、CDW12。
- **KiB / MiB / GiB**：分别为 2¹⁰ / 2²⁰ / 2³⁰ B；**KB / MB / GB** 按十进制表示。

# SSD 初始化架构与数据流

SSD（Solid-State Drive，固态硬盘） 初始化（开卡）将 NAND（NOT AND，非与型闪存） 参数、固件、坏块信息及设备身份写入系统区，使主控能够完成启动并向主机提供存储空间。本文说明各层的职责与数据流；具体命令和字段属于对应主控及桥接芯片的协议。

## 1. 物理与逻辑分层

```text
主机应用
  │ 操作系统存储接口或 USB 接口
  ▼
连接路径：原生 PCIe，或 USB → NVMe 桥接芯片 → PCIe
  ▼
SSD 主控：处理器、RAM、NAND 控制器、ECC、FTL
  │ NAND 通道与片选
  ▼
NAND 封装及内部 die / plane / block / page
```

USB（Universal Serial Bus，通用串行总线） 桥和 SSD 主控是独立芯片。桥接芯片处理 USB 与下游存储协议之间的转换，SSD 主控执行固件并管理 NAND。原生 M.2 PCIe（Peripheral Component Interconnect Express，高速串行扩展总线） 连接不经过 USB 桥。

初始化涉及主控 RAM（Random-Access Memory，随机存储器） 和 NAND 系统区的内容。桥接芯片的固件、GPIO（General-Purpose Input/Output，通用输入输出） 与供电控制属于独立功能。

## 2. 启动与维护阶段

主控通常先执行片内 BootROM，再加载外部程序。维护程序用于配置和测试介质；工作固件负责正常存储访问。程序名称、加载方式和支持的命令由主控实现决定。

以 SM2263XT 为例：

| 阶段 | 程序与位置 | 主要作用 |
| --- | --- | --- |
| ROM（Read-Only Memory，只读存储器） | 片内 BootROM | 早期启动、维护入口、接收程序 |
| MPISP | 上传到 RAM 的维护程序 | 扫描 NAND、设置参数、读写系统区 |
| ISP | 从 NAND 加载的工作固件 | 初始化介质和 NVMe（Non-Volatile Memory Express，非易失性存储接口规范） 服务，提供 namespace |

正常启动由 ROM 加载工作固件所需的引导内容；维护路径通过 ROM 上传 MPISP，写入系统区后再复位。工厂短接点及其电平含义取决于板卡设计。SM2263XT 示例板使用 P13 短接进入 ROM，正常冷启动测试需要解除短接。

运行模式与查询方法见 [SM2263XT 运行模式](../02-controller/sm2263xt/modes.md)。

## 3. 初始化数据

| 内容 | 作用 |
| --- | --- |
| 引导与工作固件 | 提供复位后执行的代码 |
| NAND 与板级参数 | 描述几何、接口时序、拓扑和功能配置 |
| 坏块与映射信息 | 标记不可用位置并分配替换空间 |
| 身份与量产信息 | 提供 PCI/NVMe 标识、序列号、型号及生产记录 |

各类数据可能分布在多个系统块中，具有独立的副本、校验和版本规则。设备启动与枚举可能同时依赖固件、参数和身份信息。

## 4. 命令通道

标准存储命令用于识别设备和访问逻辑块。厂商命令用于读取内部状态、加载程序及访问物理介质，其可用范围取决于运行模式和固件。

在 JMS583 + SM2263XT 示例路径中，主机通过 USB BOT（Bulk-Only Transport，USB 批量传输协议）（CBW（Command Block Wrapper，命令块封装） / DATA / CSW（Command Status Wrapper，命令状态封装））访问桥接芯片，再通过 A1 厂商透传提交主控的 C0/C1/C2 命令。A1 是桥接层协议，C0/C1/C2 是下游主控命令，二者属于不同层。

工作固件也可能保留部分厂商查询接口。示例设备的 ISP 模式已验证支持运行模式查询；物理扫描和擦写按 MPISP 协议执行。

## 5. 初始化主流程

```text
识别主控及运行模式
  → 选择匹配的维护程序、固件与 NAND 配置
  → 加载维护程序，读取连接拓扑
  → 派生并下发参数
  → 扫描坏块，执行所选介质测试
  → 计算容量、系统区与替换地址
  → 生成固件和系统元数据
  → 写入系统区及副本，比较写入内容
  → 复位或冷启动
  → 确认工作模式、设备身份、容量和读写结果
```

SM2263XT 示例采用 ParamTable、BBT（Bad Block Table，坏块表）、DiffAddr、InfoBlock 和 MPInfo 承载这些数据。其命令顺序与输入见 [开卡指南](../02-controller/sm2263xt/opening/card-opening-guide.md)。

## 6. 相关概念

- [术语表](glossary.md)：物理结构、程序与协议名称。
- [NAND 组织与容量](nand-geometry.md)：拓扑、几何及容量计算。
- [存储布局](storage-layout.md)：系统区、固件与量产信息。
- [坏块与地址重映射](bad-block-and-remap.md)：扫描结果、坏块表与替换空间。

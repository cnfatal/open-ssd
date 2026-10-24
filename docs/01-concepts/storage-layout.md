# SSD 系统区与用户区布局

SSD（Solid-State Drive，固态硬盘） 的 NAND（NOT AND，非与型闪存） 空间用于存放固件、系统元数据、用户数据和预留块。布局与启动规则由主控固件定义，本文先说明通用职责，再以 SM2263XT 为例说明具体结构。

## 1. 空间用途

| 区域 | 内容与职责 |
| --- | --- |
| 系统区 | 引导程序、工作固件、参数、身份与内部映射信息 |
| 用户数据区 | 由 FTL（Flash Translation Layer，闪存转换层） 管理并映射到主机 LBA（Logical Block Address，逻辑块地址） 的数据 |
| 预留空间（OP（Over-Provisioning，预留空间）） | 垃圾回收、磨损均衡和坏块替换所需空间 |
| 不可用或未分配块 | 坏块及配置未使用的位置 |

这些是用途分类，实际物理布局可能交错。系统区位置、冗余份数和选取规则不能跨主控直接套用。

## 2. SM2263XT 示例：系统块

该实现通过 ParamTable 的 P+0x20..0x23 编码四个系统位置。示例板的选取结果如下，地址均为 block 0、plane 0：

| 参数 | 内容 | 示例位置 |
| --- | --- | --- |
| P20 | InfoBlock 副本 0 | ch 0 |
| P21 | InfoBlock 副本 1 | ch 1 |
| P22 | MPInfo | ch 2 |
| P23 | IdxBlock | ch 3 |

InfoBlock 副本为系统数据提供冗余，IdxBlock 用于系统区索引。ROM（Read-Only Memory，只读存储器） 对副本的选择、有效性判断和回退行为属于启动协议，不能仅由存在两个副本推定完整规则。

## 3. SM2263XT 示例：InfoBlock

InfoBlock 将引导内容、参数、坏块信息与工作固件按页组织。各段的页边界由参数表描述符和输入长度共同决定。

本次原厂成功开卡导出的示例镜像为 101 个 16 KiB 页，共 1,654,784 B：

```text
页      内容
0       BootISP 分段
1       ParamTable P（1024 B）
2-3     BootISP 其余分段
4       SeedTable（4608 B）
5-6     OrgBad
7-8     EraseBad
9-10    TotalBad
11      CompactBad
12-15   DiffAddr
16-18   OPRom（此示例为全零）
19-28   RDT 数据
29-100  Bank：工作固件包
```

示例中的 BootISP 共 18,432 B，按 0x1800 B 分段放置；表中的页范围不代表可直接连续复制的源文件范围。工作固件包、OPRom、RDT 等段也需要按对应组包规则生成。

相关描述符包括 P+0x45、P+0x70..0x76 和 P+0xBE/0xBF。扫描结果、功能配置及固件包长度变化时，镜像页数和段位置也会变化。101 页或 104 页本身不能证明镜像正确或错误。

## 4. SM2263XT 示例：MPInfo

MPInfo 为 8 KiB，由 CID 和量产信息组成：

```text
0x0000..0x0FFF   CID：控制器身份及配置
0x1000..0x1FFF   量产信息模板及补丁字段
```

量产信息包含序列号、型号、NQN（NVMe Qualified Name，NVMe 限定名称）、统计和配置快照等字段。此实现的 +0x1400 区域保存 DriveSetting 的前 1024 B，不能用 ParamTable 替代。

MPInfo 的身份字段会参与正常启动后的枚举。项目中曾遗漏 +0x1280..0x128B 的六个 PCI/NVMe（Non-Volatile Memory Express，非易失性存储接口规范） ID 副本，使运行固件读取到零标识。系统区内容可读回、InfoBlock 校验通过，仍不足以证明原生 PCIe（Peripheral Component Interconnect Express，高速串行扩展总线） 枚举正确。字段来源见 [MPInfo 分析](../06-analysis/mpinfo.md)。

## 5. 写入与比较

系统区写入通常包括选块、擦除、按规定页序编程、写索引及比较内容。页序、写入模式、OOB（Out-of-Band，页备用区）、重复写入和副本顺序由维护程序协议决定。

SM2263XT 示例将 InfoBlock 写入 P20/P21，并在 P23 写索引；MPInfo 写入 P22。该配置的 MPInfo 写入路径覆盖 768 页，每页承载 8 KiB 内容及对应填充。768 页是该路径的配置结果，不是通用 MPInfo 大小。

主机与设备比较时，需要使用一致的地址、模式、数据范围及累加规则。比较通过证明指定范围的数据符合所用比较方法；启动还需确认引导选择、参数和身份字段等条件。

## 6. 用户数据与运行时管理

工作固件通过 FTL 维护 LBA 到物理位置的映射，并执行垃圾回收、磨损均衡和坏块替换。初始化阶段提供可用介质范围、初始坏块信息及配置，后续运行会继续更新映射和介质状态。

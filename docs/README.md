# 文档索引

安装、运行和测试见[项目README](../README.md)。厂商固件及参数原样放入 `assets/`。

## 使用与扩展

- [开卡准备](02-controller/sm2263xt/opening/prerequisites.md)
- [开卡流程](02-controller/sm2263xt/opening/card-opening-guide.md)
- [验收](02-controller/sm2263xt/opening/verification.md)、[排障](02-controller/sm2263xt/opening/troubleshooting.md)、[恢复](02-controller/sm2263xt/opening/recovery.md)
- [透传命令](05-reference/passthru.md)
- [原厂资产](05-reference/package-acquisition.md)
- [新增颗粒](05-reference/adding-a-nand.md)
- [数据来源与主流程](05-reference/design.md)

命令参数以 `python3 -m ossd --help` 及各子命令 `--help` 为准。

## 实际案例

- [SM2263XT + YMTC：开卡与原生 PCIe 验证](07-cases/sm2263xt-ymtc.md)

## 协议与原理

- 通用概念：[架构](01-concepts/architecture.md)、[术语](01-concepts/glossary.md)、[NAND几何](01-concepts/nand-geometry.md)、[存储布局](01-concepts/storage-layout.md)、[坏块与重映射](01-concepts/bad-block-and-remap.md)
- SM2263XT：[概况](02-controller/sm2263xt/index.md)、[模式](02-controller/sm2263xt/modes.md)、[协议](02-controller/sm2263xt/protocol.md)、[固件选型](02-controller/sm2263xt/firmware-selection.md)、[固件布局](02-controller/sm2263xt/firmware-areas.md)、[原厂包](02-controller/sm2263xt/package.md)
- [YMTC NAND](03-nand/ymtc/index.md)、[当前颗粒](03-nand/ymtc/x2-9060.md)
- [JMS583桥](04-bridge/jms583.md)
- [分析摘要](06-analysis/README.md)

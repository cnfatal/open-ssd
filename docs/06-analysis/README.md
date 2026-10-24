# 协议分析摘要

本文档汇总 SM2263XT 与 JMS583 的协议字段、数据来源、设备行为及验证边界。
使用流程见 [文档索引](../README.md)。

## 分析目录

| 文档 | 内容 |
| --- | --- |
| [card-mode.md](card-mode.md) | C1/90：payload 布局、N512、tail 来源及读回路径 |
| [pretest.md](pretest.md) | 扫描描述符、擦除、系统块、容量与 ParamTable |
| [save.md](save.md) | SaveInfoBlock：页计划、spare 布局、校验与 P1A 字段异常 |
| [mpinfo.md](mpinfo.md) | MPInfo 8 KiB：字段、写入与设备专属数据 |
| [cid.md](cid.md) | CID 4 KiB：子区、身份字段与时钟表 |
| [eztool-usb-gpio.md](eztool-usb-gpio.md) | EzTool GPIO：准备包、查询返回、传输修正与电源控制边界 |

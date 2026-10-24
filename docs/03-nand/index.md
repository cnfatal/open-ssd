# 颗粒系列

NAND（NOT AND，非与型闪存） 型号文档记录标识、识别方法、几何、参数行与实测结果。本文为型号和系列索引。

## 目录

| 系列 | 内容 |
| --- | --- |
| [ymtc](ymtc/index.md) | 长江存储 TAS 系列 |
| [ymtc/x2-9060](ymtc/x2-9060.md) | 项目示例配置，Flash ID 为 `9B C5 29 49 20 00` |

## 与控制器文档的职责划分

```text
02-controller/sm2263xt/   命令协议、固件选择与 InfoBlock 布局
03-nand/ymtc/x2-9060.md   NAND 标识、几何与 Flash.SET 配置行
```

同一颗颗粒可以配不同主控；同一颗主控也可以配不同颗粒。
两边交叉的地方只有一处：**Flash.SET 行 + profile**。

## SM2263XT 项目示例

```text
颗粒     ymtc/x2-9060  9B C5 29 49 20 00  8Tbit / CE=8 / 2 die
主控     sm2263xt AD
选中行   YMTC,8Tbit,YMN09TC1B1OC6C(TAS)(2Die)(SM2263XT)（Flash.SET A2）
```

## NAND 型号扩展流程

```text
1. 读 ID（C2/40）与拓扑（C2/80）
2. 在 Flash.SET 里找行；没有就补一行
3. 在 docs/03-nand/<vendor>/ 建 JSON
4. 在这里建一页文档，记录 ID、几何、SET 行、profile、实测结果
5. 按 05-reference/adding-a-nand.md 执行验证流程
```

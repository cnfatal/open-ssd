# SM2263XT 系列

本目录是 SM2263XT 主控的专属文档：协议、模式、固件选型、包结构，以及开卡流程。
通用知识见 [../../01-concepts/](../../01-concepts/)；颗粒参数见
[../../03-nand/](../../03-nand/)。

固件与参数表不在仓库里，由用户从 MPTool 包解压到 `assets/SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A/`，
见 [../../05-reference/package-acquisition.md](../../05-reference/package-acquisition.md)。

## 1. 文档范围

```text
modes.md              三种运行状态：ROM / MPISP / ISP，P13 跳线，状态判定
protocol.md           厂商命令协议：SQE 布局、逐条帧、报文样例、实现约束
firmware-selection.md 选哪份 BootISP / core0 / MPISP，按 ROM 标签与颗粒 ID
firmware-areas.md     InfoBlock 分段布局与长度派生
package.md            原厂包结构、6 份 ini、Flash.SET、LightSwitch

opening/              开卡流程
  prerequisites.md      硬件、短接、供电、权限、风险
  card-opening-guide.md 端到端命令（已实机验证）
  verification.md       五关验收
  troubleshooting.md    按现象排错 + FAQ
  recovery.md           失败恢复
```

## 2. 适用范围

| 项 | 已验证 |
| --- | --- |
| 主控 | SM2263XT AD（ROM（Read-Only Memory，只读存储器） 标签 `2263ROM:SVN02777`） |
| 颗粒 | YMTC TAS `9B C5 29 49 20 00`，8Tbit / CE（Chip Enable，片选）=8 / 2 die |
| 包 | `PKGV0217A` / `FWV0126A` / Flash.SET `V0209` |
| 桥 | JMS583（`152d:0583`） |
| 主机 | macOS arm64 实测；Linux 同接口未实机验证 |

A1/A2 修订有代码路径，但没有实机验证。换修订要重走
[firmware-selection.md](firmware-selection.md) 的判据。

## 3. 关键常量速查

```text
页大小          16 KiB（P43 = 32 个 512B 扇区）
块内页数        2304
总块数          495
数据 FBlock     398
扇区/FBlock     4,712,448
用户容量        960,197,124,096 B
BootISP         A3，18,432 B
ISP 包          core1(128 KiB) + core0_A3(1 MiB) = 1,179,648 B
InfoBlock       101 页 / 1,654,784 B
```

## 4. 启动链路

```text
ROM ──上传 MPISP──► MPISP ──写 InfoBlock/MPInfo──► 复位
                                                      │
                              ROM 读系统块 → 执行 BootISP → 加载 Bank → ISP
```

各段职责见 [modes.md](modes.md) 与 [firmware-areas.md](firmware-areas.md)。

## 5. 新增同系列主控 / 修订

```text
1. 先读 ROM 标签，确定修订与 BootISP 分支（firmware-selection.md）
2. 读 C2/40 + C2/80，确定 Flash.SET 行（颗粒 ID + CE/die 数）
3. 用 protocol.md 核对新增命令的字段
4. 实机重新执行流程 03-card-opening 的流程
```

不要把这套 opcode、页布局、ROM 标签映射直接套到 SM2260 或 SM2259 上——
它们属于不同系列，需要各自建目录。

## 6. 板级

来自原理图（`SM2263XT_BGA132X4_M2_V02_6L_T0429.pdf`），不是软件配置：

```text
启动脚    P13 / JV1      0 = ROM，1 = 正常启动；上电时采样
接口模式  P06 / R8       Legacy / Toggle（R8 0R，图纸标不贴装；实物未核）
Six ALE   P05 / R6       图纸标不贴装；未改焊
封装      2 个 NAND 封装
```

短接 P13 到 GND（Ground，地） 进 ROM；拆掉并重新上电才走正常启动。详见
[opening/prerequisites.md](opening/prerequisites.md)。

## 7. 已知未解

```text
- C1/80 末包 bit31 的设备端语义
- C2/83 mode 的完整分支
- P+0x6C（TranRTC 返回值）在固件里的实际用途
- DiffAddr 与原厂编码的逐字节差异（不影响启动）
```

# 开卡前的准备

本文列出 SM2263XT + JMS583 示例流程所需的硬件、软件、权限和输入文件。

## 1. 硬件

```text
必须
  - 一块 SM2263XT 主控的 M.2 板（本流程在 AD 修订上验证）
  - 一个 JMS583 芯片的 USB 转 M.2 硬盘盒
  - 能短接 P13 到 GND 的工具（可使用镊子、跳线帽或连接线）
  - 稳定的 USB 口（直连主机，不要用无源 hub）

建议
  - 万用表（确认短接是否导通）
  - 防静电手环
```

供电不足的典型表现：命令随机超时、扫描到一半失败、上传 MPISP 后模式读不到。
出现此类现象时，应将供电和连接稳定性纳入排查，并与软件状态分别记录。

## 2. P13 接线与启动条件

板上有一个两针跳线位（项目示例板丝印 `JV1`），一脚接 P13、一脚接 GND（Ground，地）：

```text
JV1 短接  →  P13 = 0  →  强制 ROM（开卡要用）
JV1 悬空  →  P13 = 1  →  正常启动（开完卡要用）
```

**它只在上电时被采样。** 所以：

- 进 ROM（Read-Only Memory，只读存储器）：先短接，再上电；
- 正常启动：先拆短接，再断电、重新上电。

开卡过程中保持短接即可；只有最后验收那一步才需要拆。

## 3. 软件

```sh
# macOS 安装系统 USB 库
brew install uv libusb
# Debian/Ubuntu 对应 libusb-1.0-0

uv sync --locked --extra usb

# 自检（不访问设备）
uv run ossd self-test
```

## 4. 权限

macOS 上访问 USB（Universal Serial Bus，通用串行总线） 需要 root：

```sh
sudo .venv/bin/ossd dev probe
```

Linux 上建议加 udev 规则，避免每次 sudo：

```text
# /etc/udev/rules.d/99-jms583.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="152d", ATTR{idProduct}=="0583", MODE="0666"
```

```sh
sudo udevadm control --reload && sudo udevadm trigger
```

## 5. 确认设备在 ROM

```sh
sudo .venv/bin/ossd dev probe
```

期望输出：

```text
NVMe VID: 126f
NVMe model: SM2263
NVMe firmware: 2777
```

同时系统里可能出现一个约 **1.1 GB** 的磁盘——那是 ROM 的占位容量，不是真实容量。

如果不是这个状态，先解决：
- 认不到设备 → 换口、换线、确认短接；
- 认到但型号不是 SM2263 → 核对板卡与桥接芯片型号；
- 系统报告示例目标容量 960 GB → 可能处于工作固件状态，需读取运行模式确认，检查短接是否在上电前就位。

## 6. 备份（可选但推荐）

初始化会擦写系统区并重建映射，属于破坏性操作。需要保留的原有数据应在操作前备份；初始化后不能假定原有数据仍可恢复。

## 7. 风险与恢复

| 风险 | 后果 | 能否恢复 |
| --- | --- | --- |
| 写 InfoBlock 时断电 | 盘不启动 | 能，重进 ROM 重写 |
| 参数选错颗粒 | Pretest 失败 | 可修正配置后重新执行 |
| 固件/核心选错 | 写完不启动 | 可选择匹配文件后重新执行 |
| 短接时误碰其他引脚 | 可能损坏主控 | 不能 |

在硬件正常且 ROM 维护入口可访问时，可重新加载维护程序并重建系统区。硬件损伤与维护入口不可访问的情况需单独排查。

## 8. 输入文件

从原厂包解压到 `assets/`，其余由仓库提供：

```text
$PKG/Firmware/      MPISP / BootISP A3 / ISP core0_A3 / core1 / OpRom / MPINFO
$PKG/Tables/        SeedTable2304
$PKG/DriveSetting/  DriveSettingTable_modify.bin
$PKG/FlashDB/       Flash.SET
$PKG/Config/        ini
$PKG/LightSwitch/   CID 种子

```

```sh
export PKG=assets/SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A
```

输入文件及适用范围见
[../../05-reference/package-acquisition.md](../../../05-reference/package-acquisition.md)。

下一步：[card-opening-guide.md](card-opening-guide.md)。

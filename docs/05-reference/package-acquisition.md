# 获取原厂包

仓库**不附带任何厂商文件**。把官方 MPTool 包解压到 `assets/` 即可：

```text
assets/
└── SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A/     ← 原样解压，不要改名或裁剪
    ├── SM2263XT_MPTool.exe
    ├── System.ini
    ├── Config/
    ├── FlashDB/
    ├── Firmware/
    ├── Tables/
    ├── DriveSetting/
    ├── LightSwitch/
    ├── EzTool/
    └── …
```

```sh
export PKG=assets/SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A
```

**保持原样**：不要重命名文件、不要只挑一部分拷进来。文档里的路径都直接指向包内
原始位置，这样换包版本时只要换目录名。

## 1. 初始化输入文件

| 包内路径 | 大小 | 用途 |
| --- | --- | --- |
| `Firmware/MPISP2263.bin` | 91,136 | 维护程序，上传到 RAM（Random-Access Memory，随机存储器） |
| `Firmware/BootISP2263A3.bin` | 18,432 | 引导（ROM（Read-Only Memory，只读存储器） `SVN02777` → A3） |
| `Firmware/YMTC/TAS/ISP2263XT_core0_A3.bin` | 1,048,576 | 工作固件后半 |
| `Firmware/YMTC/TAS/ISP2263XT_core1.bin` | 131,072 | 工作固件前半 |
| `Firmware/MPINFO.bin` | 4,096 | MPInfo 后半种子 |
| `Firmware/OpRom.bin` | 40,448 | 可选，占 3 页 |
| `Tables/SeedTable2304.bin` | 4,608 | C1/90 的 tail |
| `DriveSetting/DriveSettingTable_modify.bin` | 2,048 | D 模板（配置后版本） |
| `FlashDB/Flash.SET` | — | 颗粒参数库 |
| `Config/YMTC_TAS_ISP_2DIE.ini` | — | 当前选中的 profile |
| `Config/*.ini` | — | 其余 5 份参考 |
| `LightSwitch/YMTC/TAS/SM2263XT_YMTC_TAS_LightSwitch.bin` | 4,096 | CID 种子 |

## 2. 示例流程未使用的文件

| 文件 | 适用范围 |
| --- | --- |
| `Firmware/BootISP2263.bin` / `A1` / `A2` | 只适用于其他 ROM 修订 |
| `Firmware/YMTC/TAS/ISP2263XT_core0.bin` / `_A2` | 其他修订的 core0 |
| `Firmware/YMTC/TAS/ISP2263XT_RDT_core0/1.bin` | 仅用于启用 RDT 的测试路径 |
| `Firmware/SPI2263XT.bin` | 板载 SPI flash 镜像，本板不写 |
| `Tables/I2CTable.bin` | 本流程没用到 |
| `EzTool/` | 原厂小工具，本仓库不用 |
| `SM2263XT_MPTool.exe`、`SWPretestDll/` | 仅在需要原厂对照时用 |

留着不影响；它们不参与生成镜像。

## 3. 校验

```sh
ls -l $PKG/Firmware $PKG/Tables
shasum -a 256 $PKG/Firmware/MPISP2263.bin
```

长度的预期值见上表。哈希（原样解压的包）：

| 文件 | SHA-256（前 16 位） |
| --- | --- |
| `Firmware/MPISP2263.bin` | `c623d136292b040e` |
| `Firmware/BootISP2263A3.bin` | `7c4a2b998b6e46b2` |
| `Firmware/YMTC/TAS/ISP2263XT_core0_A3.bin` | `71dcac822fbbc55e` |
| `Firmware/YMTC/TAS/ISP2263XT_core1.bin` | `19f509736755ba9f` |
| `Firmware/MPINFO.bin` | `0458f0059d86b73f` |
| `Firmware/OpRom.bin` | `3a00a5ca887f7b00` |
| `Tables/SeedTable2304.bin` | `5196e27a7d830f00` |
| `DriveSetting/DriveSettingTable_modify.bin` | `a932c6a6e37192a2` |
| `FlashDB/Flash.SET` | `67620fa49c2e5a51` |
| `Config/YMTC_TAS_ISP_2DIE.ini` | `0a5195a3c886deb5` |
| `LightSwitch/YMTC/TAS/SM2263XT_YMTC_TAS_LightSwitch.bin` | `9ec3ed61dfcf15b1` |

完整值用 `shasum -a 256` 自行核对；不一致说明包被改过。

## 4. 版本一致性

```text
包名        SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A
固件        FWV0126A
Flash.SET   V0209
CID         V0126A0
```

四个版本必须来自同一个包。混用会出现"能写不能启动"。

## 5. 使用边界

```text
- 原厂包、EXE/DLL 的版权属于厂商，请按其许可使用
- 本仓库不重新分发这些文件；本文记录输入文件、目录约定及对照方法
- 固件与参数的选择规则见 02-controller/sm2263xt/firmware-selection.md
```

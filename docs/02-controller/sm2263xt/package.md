# 原厂包与配置：目录、ini、Flash.SET、LightSwitch

原厂包中的固件、参数表和配置文件共同决定初始化输入。本文以 PKGV0217A / FWV0126A 为例说明目录结构，并记录其默认配置与项目示例设备的差异。

## 1. 原厂包目录结构

```text
SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A/
├── SM2263XT_MPTool.exe          上位机
├── SM2260XTDLL.dll              预测试库
├── System.ini                   全局开关 + 选哪份 Config
├── Config/                      6 份 profile + 1 个打包文件
├── FlashDB/Flash.SET            颗粒参数数据库
├── Firmware/                    MPISP / BootISP / OpRom / SPI
│   └── YMTC/TAS/                ISP core0 / core1 / RDT
├── LightSwitch/                 4 KiB CID 种子
├── DriveSetting/                4 份 D 模板
├── Tables/                      SeedTable / I2CTable
└── File For Linux Tool/         执行完成后由工具导出的一套输入
```

`File For Linux Tool/` 在原始包里是空的，执行一次开卡后会出现 26 个文件，
包括 `ParameterTable.bin`、`DriveSettingTable.bin`、`2263XT_ISP_Package_A3.bin`
等。这些导出文件记录该次初始化实际使用的输入，可用于逐字节对照。

## 2. 六份 ini 的差异只有 5 个键

| 键 | 作用 | 取值影响 |
| --- | --- | --- |
| `FlashPartNum` | 选颗粒行 | 必须能在 Flash.SET 里找到 |
| `PretestOption` | 扫描档位 | `1` → Org 扫描 `R=0`（跳过）；`0/3` → `R=64` 全扫 |
| `ProgramRDT` | 是否执行 RDT | `1` 会做读写压测，耗时较长 |
| `KeepRDTResult` | 保留 RDT 结果 | 影响信息块里 RDT 段 |
| `DoQC` | 是否执行 QC | 增加读回校验阶段 |

其余键（`DoPretest`、`FlashClock`、`CHSelect`、`ProgramISP`、`DownloadSPI`、
`CapacityMethod` 等）六份完全相同。

**重要**：原始包里只有 `YMTC_TAS_ISP_2DIE.ini` 的 `FlashPartNum` 能在
Flash.SET 命中，而它指向的是 2Tbit/CE（Chip Enable，片选）=4 的 A0，与项目示例设备不符。该默认配置与项目示例设备不匹配，应选择 8Tbit/CE=8 的配置行（A2）。

## 3. Flash.SET 的结构

```text
[SM2263XT-DataBase-V0209]
A0=YMTC,2Tbit,YMN09TC1B1HC6C(TAS)(SM2263XT)
YMTC,2Tbit,YMN09TC1B1HC6C(TAS)(SM2263XT)=9B,C4,28,49,20,00,4,16,2048,...
```

- `A0..A5` 是别名，指向下面的长名字；
- 每行 74 列，前 6 列是颗粒 ID；
- 第 7 列起是通道数、位宽、页大小、总扇区、页/块、块数、CE 数、die 数、时序……

工具解析后打印：

```text
flash: 9B C5 29 49 20 00
geometry: page=16 spare=2048 block=1980 pages/block=2304 plane=4 ce=8 ch=2
```

在该示例中，`ce=8` 是所选 8Tbit 配置的一项核对条件，还需结合 ID、die 数和时序确认。

## 4. DriveSetting：四份模板

```text
DriveSettingTable.bin              未配置的模板（D00=45, D6C=00）
DriveSettingTable - ori.bin        同上（备份）
DriveSettingTable_modify.bin       配置后保存的版本（D00=90, D6C=07, D78=01）
oDriveSettingTable_modify.bin      另一份（D00=45, D6C=0E）
```

**项目原厂成功记录使用 `modify` 模板**，其中包含配置阶段的覆盖位：

```text
D00=90  D18=01  D3C=00  D58=01  D5C=02  D6C=07  D74=15  D78=01
```

`D6C` 和 `D78` 会被逐字节拷到 `P+D0/D1`，Boot 用它们决定初始化分支。
用未配置模板（`D6C=0`）虽然也能生成镜像，但走的是另一条启动路径。

参数生成以 `modify` 为基底，应用选中 Flash.SET 行的 69 列：

```sh
ossd param build --set Flash.SET --part "<8Tbit 行名>" \
  --template $PKG/DriveSetting/DriveSettingTable_modify.bin \
  --matrix 03000300030003000300030003000300 --internal 2 \
  --ch-mask 0x0f --ce-mask 0x05 --out-dir DIR
```

## 5. LightSwitch（CID）

4 KiB，包含 PCI/NVMe（Non-Volatile Memory Express，非易失性存储接口规范） ID、型号、序列号占位、电源/时钟/温度/安全等配置。
原厂在写 ISP 包时，会用它覆盖 core0 末尾 4096 字节。

working CID 相对静态种子只有 3 处改写：

```text
+0x008  "FWREV  "               → "V0126A0"      固件版本
+0x10C  "serial_numserial_num"  → "SN000000000000000000"
+0x128  "SMI2263XT"             → "SMI 2263XT"   型号
```

工具命令：

```sh
ossd cid identity --base $PKG/LightSwitch/YMTC/TAS/SM2263XT_YMTC_TAS_LightSwitch.bin \
  --version V0126A0 --serial SN000000000000000000 --model "SMI 2263XT" \
  --out cid-work.bin
```

上述示例的生成结果与对应厂商下发 CID 逐字节相同。

## 6. Config/*.bin 打包结构

`Config/YMTC_TAS_ISP_2DIE.bin`（约 19 KiB）是一个打包文件：

```text
偏移 0x020  RDT LS      off 0x0400  len 0x1000
偏移 0x040  ISP LS      off 0x1400  len 0x1000
偏移 0x060  LS.csv      off 0x2400  len 0x17BC
偏移 0x080  Config ini  off 0x3BBC  len 0x094D
偏移 0x0A0  DrvSetTab   off 0x4509  len 0x0800
```

包内 DrvSetTab 与 `DriveSettingTable.bin` 完全相同，是未配置模板，
不是最终 D。它的用途是"另存/导入配置"，不能拿来当生产参数。

## 7. 版本一致性

```text
包名       PKGV0217A
固件       FWV0126A
Flash.SET  V0209
CID        V0126A0
```

四个版本必须来自同一个包。跨包混用可能导致写入后无法启动。

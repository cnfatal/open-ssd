# 开卡流程（端到端）

本文以项目示例设备已执行的初始化流程为例：SM2263XT AD + YMTC TAS 8Tbit +
JMS583，macOS。命令按顺序执行，每步都写了预期输出；出现不同结果时去
[troubleshooting.md](troubleshooting.md) 查。

先读 [prerequisites.md](prerequisites.md)，确认设备在 ROM（Read-Only Memory，只读存储器）。

> 破坏性：本流程会擦除系统块、重建映射表，盘上原有数据不可恢复。

## 0. 变量约定

```sh
export PKG=assets/SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A   # 原厂包解压位置
export W=work/open            # 工作目录
export P=$W/param.bin         # 当前参数表
mkdir -p $W
```

## 1. 生成参数表 D / P

```sh
ossd param build \
  --set $PKG/FlashDB/Flash.SET \
  --part "YMTC,8Tbit,YMN09TC1B1OC6C(TAS)(2Die)(SM2263XT)" \
  --template $PKG/DriveSetting/DriveSettingTable_modify.bin \
  --matrix 03000300030003000300030003000300 \
  --internal 2 --ch-mask 0x0f --ce-mask 0x05 \
  --out-dir $W/p1
```

预期：

```text
flash: 9B C5 29 49 20 00
geometry: page=16 spare=2048 block=1980 pages/block=2304 plane=4 ce=8 ch=2
page sectors: P40..43=40 80 10 20 (P43=32, N512=33)
```

自检三个字节：

```text
D00 = 90    D6C = 07    P7E = 90
```

`D6C` 为 0 说明用错了模板（用了未配置的 `DriveSettingTable.bin`）。

## 2. 上传 MPISP

```sh
sudo ossd mpisp upload $PKG/Firmware/MPISP2263.bin --allow-ram-load
```

预期最后一行：`mode: MPISP`。

## 3. 下发参数（C1/90）

```sh
sudo ossd pretest card-mode --param $W/p1/param.bin --drive $W/p1/drive.bin \
  --out $W/dev/card-mode --allow-param-load
```

预期：

```text
readback P[0:256]: match
readback tail[0:4608]: match
readback CH map prefix: 0 1 2 3; CE map prefix: 0 2: consistent
readback: device P/tail and derived RAM state match the payload
```

## 4. 扫原始坏块

```sh
sudo ossd pretest scan-org --drive $W/p1/drive.bin \
  --pretest-option 3 --result-dir $W/scan1 --allow-scan
```

`--pretest-option 3` 让 R=64 真正执行扫描；配置里的 `PretestOption=1`
会让 R=0、直接跳过（原厂默认行为）。**空片开卡必须真扫。**

重复 2~3 次，取并集更稳：

```sh
sudo ossd pretest scan-org --drive $W/p1/drive.bin --pretest-option 3 \
  --result-dir $W/scan2 --allow-scan
sudo ossd pretest scan-org --drive $W/p1/drive.bin --pretest-option 3 \
  --result-dir $W/scan3 --allow-scan
```

## 5. 合并坏块表

```sh
ossd bbt build --scan $W/scan1 --scan $W/scan2 --scan $W/scan3 \
  --param $W/p1/param.bin --policy union --out $W/p2
```

预期形如：

```text
bbt: policy=union runs=3 T=495 bad_rows=18 bad_bits=66
```

## 6. 擦除复扫

```sh
sudo ossd pretest erase-run --param $W/p1/param.bin --drive $W/p1/drive.bin \
  --bbt $W/p2/bbt.bin --pretest-option 3 --out $W/erase --allow-erase
```

该步骤执行物理块擦除。完成后将**新增坏块合并至 BBT（Bad Block Table，坏块表）**，再重算容量：

```sh
ossd bbt build --scan $W/scan1 --scan $W/scan2 --scan $W/scan3 \
  --param $W/p1/param.bin --policy union \
  --erase $W/erase/erase-result.bin --out $W/p2
```

`--erase` 让最终表 = `org | erase`，但 `P+3E` 仍只数 org 的行——这是
原厂口径：系统块按候选顺序选择；可通过 `--probe` 执行试写校验。

> 注意：`erase-run` 会擦掉第 0 批里的系统块。已初始化设备重新执行前需明确其擦除范围，
> 否则 InfoBlock 会被抹掉，需要重新写（盘会退回 ROM）。

## 7. 系统块与容量

```sh
ossd layout system --param $W/p2/param-after-bbt.bin --bbt $W/p2/bbt.bin \
  --fill --out $W/p3
ossd layout capacity --param $W/p3/param-system-candidate.bin \
  --drive $W/p1/drive.bin --out $W/p4
```

预期：

```text
system: wrote unprobed P+20..P+27 and P+30=1
capacity: data=398 nominal=8177 reserve=53 surplus=46
capacity: sectors_per_fblock=4712448 total_sectors=1875385008
```

> `layout system --fill` 只按"未被 BBT 标记"挑 8 个候选，不代表已实测。
> 想逐个验证用 `pretest probe-run`。

## 8. 生成 DiffAddr

```sh
ossd diffaddr build --param $W/p4/param-capacity.bin --drive $W/p1/drive.bin \
  --bbt $W/p2/bbt.bin --compact $W/p2/bbt-compact.bin --out $W/p5
```

预期：

```text
diffaddr: n1=12 n2=0 total=12 bad_rows=6
```

## 9. 重算容量（用 DiffAddr 后的坏块数）

```sh
ossd layout capacity --param $W/p5/param-after-diffaddr.bin \
  --drive $W/p1/drive.bin --out $W/p6
```

## 10. 生成 working CID 与 ISP 包

```sh
ossd cid identity --base $PKG/LightSwitch/YMTC/TAS/SM2263XT_YMTC_TAS_LightSwitch.bin \
  --version V0126A0 --serial SN000000000000000000 --model "SMI 2263XT" \
  --out $W/cid-work.bin

ossd isp package \
  --core0 $PKG/Firmware/YMTC/TAS/ISP2263XT_core0_A3.bin \
  --core1 $PKG/Firmware/YMTC/TAS/ISP2263XT_core1.bin \
  --lightswitch $W/cid-work.bin --manufacturer YMTC --out $W/isp
```

预期：

```text
cid identity: bytes=4096 changed=33
isp package: bytes=1179648 boot_start=0xe0000 format=03 mfg=da sha=0
```

## 11. 生成 InfoBlock

```sh
ossd infoblock build \
  --param $W/p6/param-capacity.bin \
  --boot $PKG/Firmware/BootISP2263A3.bin \
  --seed $PKG/Tables/SeedTable2304.bin \
  --org $W/p2/org-combined.bin \
  --erase $W/erase/erase-result.bin \
  --total $W/p2/bbt.bin --total-bytes 0x8000 \
  --compact $W/p2/bbt-compact.bin \
  --diff $W/p5/diffaddr.bin \
  --oprom-bytes 0x9E00 \
  --rdt $W/rdt.bin \
  --bank $W/isp/sm2263xt-isp-package-a3.bin \
  --out $W/ib
```

`--rdt` 是项目示例设备已有的 RDT 结果前 160 KiB；没有 RDT 数据时省略该参数，
descriptor 会相应前移。

预期：

```text
infoblock: pages=101 sectors=3232 descriptor=0,1,3,2,4,5,7,204,9,11,12,16,19,29,37
```

## 12. 生成 MPInfo

2026-10-24：旧 C builder 漏了六个 PCI/NVMe（Non-Volatile Memory Express，非易失性存储接口规范） ID 副本，不能再将它生成的 MPInfo 用于开卡。
下面使用已修正的 Python builder：`+1400` 输入为 DriveSetting 前1024B，物理写入命令
仍用独立 P。当前修正尚未进行自生成镜像的原生 M.2 重刷复测。

```sh
python3 -m ossd mpinfo build --cid $W/cid-work.bin \
  --seed $PKG/Firmware/MPINFO.bin \
  --drive $W/p1/drive.bin \
  --typemap $W/ib/infoblock-typemap.bin \
  --cid-final $W/cid-work.bin \
  --sn AA000000000000000002 --model "SMI 2263XT" \
  --nqn "nqn.2026-10.com.smi:nvm-subsystem-sn-AA000000000000000002" \
  --version V0126A --time 202610231830 --counter 1 \
  --out $W/mpinfo
```

## 13. 重新下发最终参数

InfoBlock 生成时往 P 里回填了 descriptor 等字段，所以要用**最终 P** 再下一次：

```sh
sudo ossd pretest card-mode --param $W/ib/param-after-infoblock.bin \
  --drive $W/p1/drive.bin --out $W/dev/card-mode2 --allow-param-load
```

## 14. 写 InfoBlock

```sh
sudo ossd infoblock save-run \
  --param $W/ib/param-after-infoblock.bin \
  --info $W/ib/infoblock.bin \
  --typemap $W/ib/infoblock-typemap.bin \
  --out $W/dev/save --allow-save
```

预期最后一行：

```text
compare: host=0x........ device0=0x........ device1=0x........: match
```

三个值相同表示指定数据范围的累加比较通过；不匹配时应核对地址、数据范围、读写模式和读回内容，再确定修正措施。

## 15. 写 MPInfo

```sh
sudo ossd mpinfo write --mpinfo $W/mpinfo/mpinfo.bin \
  --param $W/ib/param-after-infoblock.bin --out $W/dev/mpinfo --allow-mpinfo

sudo ossd mpinfo verify --mpinfo $W/mpinfo/mpinfo.bin \
  --param $W/ib/param-after-infoblock.bin --out $W/dev/mpinfo
```

预期：`mpinfo verify: host=0x... device=0x...: match`。

## 16. 复位并冷启动

```sh
sudo ossd dev reset --allow-reset
```

然后**物理动作**：

```text
1. 拆掉 P13 短接
2. 断电
3. 重新上电
4. 等 2~3 秒，系统应出现一个约 960 GB 的磁盘
```

## 17. 验收

见 [verification.md](verification.md)。

## 附：已有扫描结果的复用条件

若目标设备的 Org/Erase 扫描结果已验证，且介质与配置未发生变化，
可以跳过第 4~6 步，直接用已有的 `bbt.bin` / `org-combined.bin` /
`erase-result.bin`。项目实机记录曾复用此类扫描输入；参数和布局发生变化时，
但扫描结果与参数无关。

不能复用的是：`param.bin`（含坏块数）、`diffaddr.bin`、`infoblock.bin`、
`mpinfo.bin`，这些都要按当前数据重新生成。

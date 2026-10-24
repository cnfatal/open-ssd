# 初始化验收标准与测试方法

验收包括容量、访问权限、读写和冷启动持久性。以下命令以项目示例设备为例：容量为 960,197,124,096 B，macOS 设备节点为 disk4。执行时需使用目标设备的实际节点和预期容量。

## 1. 容量匹配

```text
期望：960,197,124,096 字节 = 1,875,385,008 × 512
```

macOS：

```sh
diskutil info disk4 | grep -E "Disk Size|Device Block Size|Media Read-Only"
```

期望：

```text
Disk Size: 960.2 GB (960197124096 Bytes) (exactly 1875385008 512-Byte-Units)
Device Block Size: 512 Bytes
Media Read-Only: No
```

Windows：

```powershell
Get-Disk | Format-List Number,FriendlyName,Size,PartitionStyle,HealthStatus
```

期望 `Size : 960197124096`，`PartitionStyle : RAW`（未分区是正常的）。

容量不匹配时，应核对目标容量、运行模式、参数表中的块数、坏块统计及预留策略，并区分 GB/GiB 显示单位。

## 2. 分区状态与写入权限

```text
Content / PartitionStyle = None / RAW   ← 正常
Media Read-Only = No                    ← 必须
```

如果显示只读，通常是固件认为介质异常（比如坏块表不可信）。

## 3. 读取测试

```sh
sudo dd if=/dev/rdisk4 bs=512 count=1 2>/dev/null | od -A x -t x1
```

记录实际读取的 512 B 及 I/O 状态。未写入逻辑块的返回内容由固件实现决定，不能将全零作为通用验收条件。单次读取成功仅验证该范围的读取路径。

## 4. 写入与读回比较

以下示例向首个逻辑块写入已知图案并读回比较，会覆盖该位置的原有内容；仅用于允许覆盖的测试设备：

```sh
python3 -c "open('pat.bin','wb').write(bytes((i*7+0x5A)&0xFF for i in range(512)))"
sudo dd if=pat.bin of=/dev/rdisk4 bs=512 count=1
sync
sudo dd if=/dev/rdisk4 bs=512 count=1 2>/dev/null | od -A n -t x1 | head -2
```

期望前 16 字节：

```text
5a 61 68 6f 76 7d 84 8b 92 99 a0 a7 ae b5 bc c3
```

对于原先为空且允许清零的测试位置，可执行以下清零操作；清零不等于恢复原始内容：

```sh
dd if=/dev/zero of=zero.bin bs=512 count=1
sudo dd if=zero.bin of=/dev/rdisk4 bs=512 count=1
```

该测试验证指定逻辑块的写入与读回路径，不能单独证明全部 FTL（Flash Translation Layer，闪存转换层） 映射或整盘可靠性。

## 5. 冷启动与持久化测试

```text
断电 → 等 3 秒 → 上电 → 容量、读写再测一次
```

至少重复一次冷启动，并分别记录身份、容量与读写结果，以观察启动和持久化行为是否可重复。

## 判定表

| 现象 | 结论 |
| --- | --- |
| 容量精确、RAW、读写通过、两次冷启动都正常 | ✅ 成功 |
| 容量对但只读 | ❌ 介质/坏块表异常 |
| 容量对但写失败 | ❌ FTL 或 DiffAddr 有问题 |
| 容量是 1.1 GB | ❌ 还在 ROM（Read-Only Memory，只读存储器）（短接没拆或没重新上电） |
| 容量是 960 GB 但第一次冷启动后消失 | ❌ 固件不稳，检查 InfoBlock 两份副本 |

## 验收记录

验收记录包含以下内容，用于后续对照：

```text
开卡日期
D / P 的哈希
InfoBlock 页数 + descriptor
save 的 compare 三个值
mpinfo verify 的值
开卡后容量与读写结果
```

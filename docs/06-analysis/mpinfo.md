# MPInfo：8 KiB 的组成与写入

## 1. 结构

```text
0x0000..0x0FFF   CID（4 KiB）
0x1000..0x1FFF   MPINFO 种子（4 KiB，文件头是 "MPINFO"）
```

整体 8192 B，写入时每页复制同一份 8 KiB 再补零。

## 2. 关键字段

| 偏移 | 含义 |
| --- | --- |
| `0x0008` | 版本（如 `V0126A`） |
| `0x1200` | 序列号（20 字符） |
| `0x1214` | flags（bit13 = 有 NQN（NVMe Qualified Name，NVMe 限定名称）） |
| `0x1220` | 型号（"SMI 2263XT"） |
| `0x130E` | 量产计数器 |
| `0x1350` | typeMap 的游程编码 |
| `0x1280..0x128B` | CID 中六个 PCI/NVMe（Non-Volatile Memory Express，非易失性存储接口规范） ID 的副本；生产者置 flags 0xFE0 |
| `0x1400` | 导出时 DriveSetting 的前 1024 B 快照 |
| `0x1800` | NQN |
| `0x1900` | 统计（读/写/坏块） |
| `0x1910` | 时间戳（BCD，如 `202610231830`） |

原 EXE 的 4453DD..4453EE、445F98、446762 将 DriveSetting 导出表的前1024B
写到 `0x1400`；原厂成功样本也与导出的 D 前1024B逐字节一致。
旧文档将这里写成 P，是错误的。InfoBlock 内的 P 与 MPInfo 内的 D 是不同对象。

Python 已修复六个 ID 副本、其 0xFE0 有效位、model有效位与空格填充，生成入口使用
`--drive D.bin`。EUI/NGUID及其他生产字段仍未全部实现，不能将这些修复称为完整MPInfo生产链。

## 3. 写入

```text
目标     P22
擦除     mode 85h
页数     P[48h] = 768
每页     payload = 8 KiB + 补零到 16 KiB
spare    E7 标签（plane*32 + 0 与 +0x10 各一个）
写页     C1/83 mode C5
```

校验用 `C2/8D82`：设备对 768 页主数据做累加，结果应与主机计算的相同。

```sh
ossd mpinfo write --mpinfo M.bin --param P.bin --out DIR --allow-mpinfo
ossd mpinfo verify --mpinfo M.bin --param P.bin --out DIR
```

## 4. 生成流程

```text
1. 取 working CID（4 KiB）
2. 取 MPINFO 种子（4 KiB）
3. 拼成 8 KiB
4. 打补丁：版本、SN、型号、NQN、flags、计数、时间、统计
5. 生成 typeMap 的 RLE（0x1350）
6. 写入 DriveSetting 前1024B快照（0x1400）
```

工具一条命令完成：

```sh
python3 -m ossd mpinfo build --cid C.bin --seed S.bin --drive D.bin --typemap T.bin \
  --sn AA... --model "SMI 2263XT" --nqn nqn.… --version V0126A \
  --time 202610231830 --counter 1 --out DIR
```

## 5. 与厂商导出物的差异

同一轮里，`File For Linux Tool/MPInfo2263XT.bin`（模板）与实际下发的
8 KiB 相差 41 字节，全部是每盘字段：

```text
0x1011        ID 尾字节
0x1213        SN 末位
0x130E        计数器
0x1350..1364  typeMap RLE
0x1842        NQN 末位
0x1900..1904  统计
0x1910..191B  时间
```

导出的 MPInfo 模板不能直接替代最终写入内容，因为其中尚未补齐设备专属字段。

## 6. 边界

- 主机路径里没有对 8 KiB 的整体 checksum；不能把 `0x1214`（flags）
  或 `0x130E`（计数）误标成校验字段。
- 写页 handler 只做物理写入，不校验 SN/NQN 语义；这不等于固件复位后
  接受任意内容。
- 旧 MPInfo 读取失败时的"恢复分支"与正常生成路径是两条链路，不要混用。

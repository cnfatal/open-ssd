# 失败恢复

系统区写入失败后，在硬件正常且片内 ROM（Read-Only Memory，只读存储器） 维护入口可访问的条件下，可重新加载维护程序。本文按枚举和响应状态说明恢复路径，具体容量与配置以项目示例设备为例。

## 1. 判断当前状态

```sh
# 查询外置磁盘与容量
diskutil list | grep -A3 external

# 查询 USB 桥接芯片枚举
ioreg -p IOUSB -l | grep -i jms

# 查询主控运行模式
sudo ossd read mode
```

| 现象 | 状态 | 对应章节 |
| --- | --- | --- |
| 有 960 GB 盘，读写正常 | 已成功 | 无需恢复 |
| 有 1.1 GB 占位 | ROM | 2 |
| 没有盘，但 `read mode` 能读 | ROM/MPISP | 2 |
| 没有盘，`read mode` 超时 | 主控异常或桥无响应 | 3 |
| 完全看不到 USB（Universal Serial Bus，通用串行总线） 设备 | 供电/接触问题 | 4 |

## 2. 恢复 ROM 维护入口

```text
1. 短接 P13 到 GND
2. 断电
3. 上电
4. sudo ossd dev probe        → 应看到 SM2263 / 2777
```

随后按流程重新执行 [card-opening-guide.md](card-opening-guide.md)。

## 3. 主控不响应

如果 `dev probe` 返回 `reason=12 fault=6` 一类超时：

```sh
# 尝试 USB 传输恢复，保持物理连接
sudo ossd dev usbreset
sleep 3
sudo ossd dev probe

# 恢复失败时完整断电，等待 5 秒后重新连接
```

断电时**短接要保持连接**，否则上电会走正常启动路径。

如果连续多次都不响应：检查供电（换口/换有源 hub）、检查板子是否过热、
确认桥本身在其他主机上是否正常。

## 4. USB 设备未枚举

```text
- 换 USB 线
- 换 USB 口（优先直连主板后置口）
- 换一个 JMS583 硬盘盒（桥本身可能坏）
- 检查 M.2 金手指是否氧化/未完全插入
```

## 5. 原厂工具对照流程

自研流程写入后无法启动时，可使用原厂 MPTool 执行对照，并记录配置、测试阶段及启动结果：

```text
1. 短接 P13，上电，确认工具识别到盘
2. Config 选 YMTC_TAS_ISP_2DIE
3. 确认 Flash 选的是 8Tbit（9B C5 29 / CE=8），不是默认的 2Tbit
4. 开始
```

关键：**原厂包的默认 `FlashPartNum` 是 2Tbit（9B C4 28 / CE（Chip Enable，片选）=4），与项目示例设备不匹配。**
沿用该配置可能导致 Pretest 失败于第 8 项 `FlashConnectivity`。

改法：编辑 `Config/YMTC_TAS_ISP_2DIE.ini`：

```ini
FlashPartNum=YMTC,8Tbit,YMN09TC1B1OC6C(TAS)(2Die)(SM2263XT)
```

原厂工具执行完成后会在 `TestResult/PtestLogFile_Drive<日期>/` 留一整套 dump，
以及 `File For Linux Tool/` 一套导出文件——这些可以用来对照本工具生成结果。

注意：原厂工具在短接状态下 `CheckISP` 会报 Fail，这是正常的；拆短接冷启动
能出盘即可。

## 6. 恢复结果确认

```text
- 容量是否 960,197,124,096
- 是否 RAW / 非只读
- 读写是否正常
- 再冷启动一次是否仍然正常
```

## 7. 恢复能力边界

```text
- 短接时误碰了其他引脚，主控被击穿
- 供电接反
- NAND 本身物理损坏
```

此类故障超出系统区重写的处理范围。ROM 可响应是进入维护流程的条件之一；重新初始化还依赖介质、供电及后续程序执行正常。

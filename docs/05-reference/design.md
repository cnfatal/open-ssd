# 数据来源与主流程

## 唯一可信源

| 数据 | 来源 |
|---|---|
| 原厂配置、几何与时序 | 包内 System.ini、Config/*.ini、Flash.SET |
| 固件、D/CID种子与SeedTable | 同一原厂包对应文件 |
| ROM（Read-Only Memory，只读存储器）修订、NAND（NOT AND，非与型闪存） ID、拓扑、RTC、坏块 | 当前设备实读 |
| 明确覆盖原包的选择 | 命令行参数 |

不另存一份板卡profile、几何JSON或固件白名单。当前包默认颗粒行与实盘不符时，
使用显式 `--part A2`，不修改本地原包。包目录可直接复制到 `assets/`，不需要专用导入脚本。

## 单向数据流

```text
原厂包 + 实盘读数 + 显式覆盖
→ 选择固件与颗粒行
→ D / P / CID
→ 扫描、BBT、系统块、DiffAddr
→ 容量、InfoBlock、MPInfo
→ 设备写入、Compare、复位、启动验收
```

生成器输入字节并返回产物；主流程继续传递内存中的结果，保存文件用于分析，
不读回刚写出的文件充当另一份配置。DiffAddr成功后回填P+3E，容量计算消费该结果。
D与P是不同对象：MPInfo+1400为D前1024B，InfoBlock及物理操作使用P。

## 模块职责

- `ossd/config/` 解析原厂文件，`select.py` 结合实盘信息选择。
- `generator/` 生成和解码字节，不访问设备。
- `transport/` 处理USB（Universal Serial Bus，通用串行总线）、BOT（Bulk-Only Transport，USB 批量传输协议）和JMS583封装。
- `device.py` 组合设备命令，`stages/` 组合生成与保存操作。
- `open_flow.py` 编排开卡步骤，`cli.py` 提供入口。

流程依照协议与设备结果推进，不增加额外授权开关、哈希白名单或无差别重试。
失败保留实际错误；写入和启动验收分别记录，Compare通过不等于固件格式或启动正确。

## 当前边界

目前生成流程针对SM2263XT AD及YMTC TAS组合。RDT生产测试、EUI/NGUID等部分
原厂生产字段尚未完整实现。不能以旧C生成结果为唯一正确答案；生产字段以原厂
指令、实际导出和设备消费路径对照。协议细节见主控目录，已知缺口见分析摘要。

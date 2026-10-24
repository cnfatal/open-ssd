# EzTool USB GPIO：读取命令与返回值还原

2026-10-24。来源：TAS PKGV0217A/FWV0126A 包内 `EzTool/EasyTools_2263.exe`，32-bit PE，ImageBase `400000h`。先完成原 x86 离线执行，随后完成本文第8节的当前JMS583只读查询实测。

结论：GPIO（General-Purpose Input/Output，通用输入输出）查询编码与单值返回布局已闭合；当前JMS583已接受selector=2、device_word=10000h的查询，返回value=1。GPIO是否接到供电开关、Power ON/OFF是否实际断电，仍未实测。

## 1. ON/OFF 操作与传输阶段

`3B FF 00` 和 `3B FF 01` 不是分别代表 ON/OFF。原工具的每次 GPIO **写操作**都发送这两个阶段：第一阶段选择查询/操作目标，第二阶段发送 `GPIO` 及值。

原工具的 GPIO **读操作**是：

```text
OUT  3B FF 00 00 00 00 00 04 00 00    准备，1024B
IN   3C FF 01 00 00 00 00 04 00 00    取返回，1024B
```

`3Bh` 为 WRITE BUFFER，`3Ch` 为 READ BUFFER。这条读取需要一次 OUT 准备，不是 NVMe（Non-Volatile Memory Express，非易失性存储接口规范） A1 透传；OUT 准备中没有第二阶段的 GPIO 输出值。不应为了追求“USB（Universal Serial Bus，通用串行总线） 全程只有 IN”而省略它。控制器端是否存在其他副作用未验证。

## 2. 从 GUI 到实际读取的调用链

Delphi 方法表中的 `BTN_Main_GPIO_GetClick` 指向 `477694h`。函数从 GPIO ID 输入框取得数字，将它作为 selector，调用：

```text
47774E: call 40D04C(outer_device, selector, uint32_out)
  40D04C: 取 outer_device+4 的内部设备指针
  405C58: 调用通用1024B查询，取返回的一个值
  405B10: 组准备包、发送、接收并验证签名
    404B78: 构造 WRITE BUFFER CDB
    404A04: 构造 READ BUFFER CDB
```

这说明 selector 来自界面输入，不能由本次逆向直接断定只有 2/5 有效，也不能给其他 selector 随意命名。

## 3. 准备包

`405B10h` 先清零整个1024B缓冲，再写两个字段：

| 偏移 | 长度 | 内容 | 原指令 |
| --- | --- | --- | --- |
| `00h..3Fh` | 64B | 0 | `405B69..405B7C` 清零整包 |
| `40h` | 4B | 内部设备结构 `+19Ch` 的 DWORD，原样小端复制 | `405B7F..405B97` |
| `44h` | 1B | selector 的低字节 | `405B9A..405B9D` |
| `45h..3FFh` | 955B | 0 | 同一清零操作 |

结构 `+19Ch` 的初始化值是 `00010000h`，setter `403FD8h` 也将输入0替换为该值。它不是 GPIO pin 编号；本轮只闭合来源和字节编码，不给它追加已确认的设备端语义。运行时可以被 setter 覆盖，因此不能把初始化值宣称为所有桥上固定常量。

准备发送后，原代码检查底层返回值；失败直接退出，不执行 READ BUFFER。

## 4. 返回布局与解析

`405BFAh` 调用 READ BUFFER，长度为1024B，返回布局中已证明被消费的部分如下：

| 偏移 | 长度 | 已证明含义 |
| --- | --- | --- |
| `00h..03h` | 4B | ASCII `GPIO`，`47 50 49 4F` |
| `04h` | 1B | 单值查询显示的值，按无符号8位读取 |
| `05h..3FFh` | 1019B | 通用单值读取不解析；不能命名为全零、保留区或另一种状态表 |

两层原始处理：

1. `405B10h`：传输成功后，`405C0B..405C23` 比较前4B；签名匹配才把整个1024B复制到调用方缓冲，签名错误返回false。
2. `405C58h`：再次比较签名；`405C97` 读取缓冲 `+4` 的BYTE，随后 `AND FFh`，写入调用方DWORD。值 `80h` 和 `FFh` 分别变成128和255，不做有符号解释。

因此解析规则为：

```python
value = reply[4]  # 不是 LE16(reply[4:6])
```

原程序未通过返回头验证响应与请求 selector 的对应关系，目前没有证据证明返回包含 selector echo 或 checksum。也不应把 `value` 无条件压成布尔值；0/1之外的字节原程序按原始数值显示。

还有一条不同消费路径：`404284h` 以 selector=7调用 `405B10h`，随后取返回 `+0Dh` 起30B。说明该协议存在 selector 对应的其他数据用途，不能把整个1024B统一定义成一个GPIO状态字或位图。

## 5. 原程序失败路径的限制

GUI（Graphical User Interface，图形用户界面） 在 `47774Eh` 调用后没有检查返回的bool，直接显示输出DWORD。`405C58h` 自己也会在通用查询返回false后继续检查局部缓冲。因此失败时的界面数字不能当作可靠设备状态。

新实现应以传输成功和签名匹配为解码前提；错误时保留原始数据和错误结果，不应沿用原 GUI 可能残留的显示值。这是上述协议已有的成功条件，不需要另加未知字段、hash或其他判定。

## 6. 已完成的离线验证

离线指令仿真执行原 EXE 的 `40D04C/405C58/405B10/404B78/404A04` 指令；仅替换已打开设备检查、内存辅助函数和Windows发送接口。底层接口记录真实构造出的CDB及payload，读取时注入测试返回。

共32组执行，覆盖：

- selector=0/2/5/7/255；这只是编码测试，不声称设备支持这些值。
- value=0/1/127/128/255；返回 `+5=FEh`，证明单值解析只取 `+4`。
- 完整准备包1024B逐字节比对；两条CDB、传输方向和长度。
- 通用读取返回完整1024B，与单值接口返回DWORD分别核对。
- 准备发送失败、读取失败和错误签名。
- `+19Ch=12345678h` 时按小端写入 `+40h`，没有写死默认值。

结果：32 组测试全部通过。纯离线协议模型同时验证构帧与解析，不调用 USB。此验证证明主机端构帧与解析，不证明真实桥执行了命令。

## 7. M4 剩余工作

可关闭的缺口：读取CDB、准备payload字段来源、返回签名、单值偏移及宽度、主机失败路径。离线编码器和解析器已可实现。

本节原列出的“当前桥是否支持”和“实际读取”已由第8节的selector=2实测推进；其他selector仍未验证。仍待完成设备类型位映射、结构字段设备端意义，以及selector与物理GPIO/供电接线的对应关系。

下一次现场验证应以已确定的适用条件为前提，执行一次“准备+读回”，保存两个BOT（Bulk-Only Transport，USB 批量传输协议）结果和原始1024B，不发送GPIO写值、Power ON/OFF或复位。若适用条件尚不能确认，继续追设备识别路径，不向用户设备遍历未知selector。

## 8. 真机查询与Python传输修正

后续排查发现Python初版实现存在三个具体偏差：

- `READ_CDB`只有9B，缺少一个00；长度字段错位为262144，而原CDB为10B、长度1024。
- `device_word`默认填0，未采用已还原的原程序初始化值10000h。
- 所谓原始SCSI被包在自造的`SCSI`容器中，再通过A1三阶段发送。原程序实际走Windows SCSI Pass-Through，将3B/3C直接作为CDB。旧返回status=1不能证明GPIO准备包参数被拒，甚至不能证明3B已作为USB侧CDB提交。

原EXE `402F80h`填充32位 `SCSI_PASS_THROUGH_DIRECT`，把CDB复制到结构+1Ch，在`403068h`使用IOCTL `4D014h`提交。内部设备`+19Ch`同时写入结构`+10h`，即Windows的TimeOutValue；其在GPIO payload中的设备端语义仍未证明。[微软结构定义](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntddscsi/ns-ntddscsi-_scsi_pass_through_direct)

修正后的原始SCSI使用单次CBW（Command Block Wrapper，命令块封装）/data/CSW（Command Status Wrapper，命令状态封装），CBW的CDB字段直接为3B/3C，复用已有BOT发送与CSW检查。首先实测标准INQUIRY和READ CAPACITY，均CSW=0；随后执行一次selector=2的查询：

```text
device_word=00010000h → payload[40:44] = 00 00 01 00
selector=2           → payload[44]    = 02
3B/FF/00 OUT 1024B   → CSW 55534253010000000000000000
3C/FF/01 IN  1024B   → CSW 55534253020000000000000000
reply[0:5]           = 47 50 49 4F 01  → GPIO, value=1
```

之后正式CLI（Command-Line Interface，命令行接口）再次返回`gpio selector=2 value=1 (0x01)`；Identify仍为SMI 2263XT/V0126A0，系统恢复列出960.2GB的disk4。没有发送GPIO输出值、Power ON/OFF、SSD（Solid-State Drive，固态硬盘）复位或NAND（NOT AND，非与型闪存）写入。

另外已用“只open/close、不提交任何存储命令”复现disk消失：detach_kernel_driver时disk4消失，原close只release、未attach。补上驱动归还后，不拔插也能重新出现disk4；重新枚举可能稍晚于attach返回。该现象不能一概称为SSD故障或“vendor命令令桥锁死”。

没有分别对零device_word和错误A1封装做真机负面对照，因此不把先前拒绝唯一归因于某一处错误。当前实测证明的是修正后完整查询序列有效。

窗口抓包仍可用于核对实际覆盖值和电源动作，但GPIO读取已不再被抓包阻塞。

## 9. 电源序列测试的实际结果

用户随后授权测试原EzTool序列。OFF的2=1、ON的5=0及2=0均取得CSW=0，但整个ON序列后SSD未响应；恢复2=1、改变5=1和USB reset均未恢复。失败TUR后立即REQUEST SENSE取得04h/44h/81h。没有电压测量，不能将上述值直接映射为供电引脚电平，也不能唯一断言5=0或2=0是哪条致因。

最终用户完整断电重接后，型号、固件、SN、960197124096B容量和ISP模式恢复，media_errors与error_log_entries均为0。原序列未达到当前盒子上可靠的软件OFF/ON验收，因此仍不发布电源CLI。

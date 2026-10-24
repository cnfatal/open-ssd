# assets/

放**原厂 MPTool 包的原样解压结果**。仓库不分发这些文件，所以本目录默认被
`.gitignore` 排除（只保留这个 README）。

```text
assets/
└── SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A/
    ├── SM2263XT_MPTool.exe
    ├── System.ini
    ├── Config/  FlashDB/  Firmware/  Tables/  DriveSetting/  LightSwitch/
    ├── EzTool/  SWPretestDll/ …
```

**不要改名、不要裁剪**。文档里的路径直接指向包内原始位置。

## 目录放置方式

```sh
# 解压官方包后
cp -R /path/to/SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A assets/
```

直接复制整个包目录即可，不需要专用导入脚本。

## 初始化输入文件

包内并非所有文件都参与开卡。用到的 12 个文件、以及不用的（RDT core、SPI、
其他修订的 BootISP 等）见
`docs/05-reference/package-acquisition.md`。

## 说明

- 换包版本时目录名跟着变，命令里用 `$PKG` 变量；
- 这个目录可以随时删除，重新解压即可恢复；
- 版权归厂商，仓库不重新分发。

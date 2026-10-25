# open-ssd — SM2263 跨平台开卡工具

Open-source, cross-platform alternative to Silicon Motion MPTool.

慧荣 **SM2263 系列**的 MPTool 替代工具，使用 Python 编写，支持 macOS、Linux 和 Windows。
提供参数生成、坏块扫描、固件组包与系统区写入。

## 安装

运行时支持 Python 3.10+，开发环境使用 `.python-version` 指定的 Python 3.15。
使用 [uv](https://docs.astral.sh/uv/guides/projects/) 管理环境、依赖和构建，USB 访问需要系统 libusb。

```sh
# macOS；其他系统按 uv 官方说明安装，并安装对应的 libusb 软件包
brew install uv libusb
uv sync --locked --extra usb
uv run ossd --help
```

`uv.lock` 固定依赖，开发依赖在 `pyproject.toml` 的 `dev` 组中；无需手动创建或激活虚拟环境。
仅使用离线功能时可运行 `uv sync --locked`，不安装 USB 扩展。

## 开发检查

```sh
uv run ruff format .          # 格式化
uv run ruff check .           # lint、导入顺序和 Python 写法检查
uv run ruff check . --fix     # 应用 Ruff 的安全自动修复
uv run pyright                # Pylance 同源的类型检查
uv run pytest -q              # 测试
uv build                     # 生成源码包和 wheel
```

提交前检查格式使用 `uv run ruff format --check .`。
[Ruff](https://docs.astral.sh/ruff/) 的格式与 lint 配置、pytest 的测试目录都在 `pyproject.toml`。
类型检查由 [Pyright](https://github.com/microsoft/pyright) 执行，与 Pylance 共用
`pyproject.toml` 中的 standard 规则，覆盖 `ossd/` 和 `tests/`，排除资产和历史归档。
CI 在 Linux、macOS、Windows 上执行相同检查，并在 Linux 检查 Python 3.10 兼容性。

测试使用现有 unittest 用例，由 pytest 统一收集。部分原厂产物回归依赖本地 `assets/`、
`tmp/` 夹具，缺失时跳过；默认不会连接设备。`uv run ossd self-test` 仍可运行原有离线自检。

## 设备与开卡

```sh
sudo .venv/bin/ossd dev scan
sudo .venv/bin/ossd dev probe
```

开卡会擦写 NAND。当前实测组合为 SM2263XT AD、YMTC TAS `9B C5 29 49 20 00`、
8 CE / 每 CE 2 die、JMS583。将原厂包原样放入 `assets/`，短接 P13 上电进入 ROM 后：

```sh
sudo .venv/bin/ossd open \
  --package assets/SM2263XT_YMTC_TAS_PKGV0217A_FWV0126A \
  --part A2 --pretest-option 3 --probe --work tmp/open-python
```

程序提示后断电，拆掉 P13 短接，再接回继续验收。

MPInfo 六组 PCI/NVMe ID 副本的遗漏已修复，并通过原指令离线对照；
修正版尚未重刷做原生 M.2 验收。当前原厂开卡盘已在 Linux M2.2 实测 Gen3 x4。
字段来源与生成规则见 [MPInfo 协议分析](docs/06-analysis/mpinfo.md)。

## 目录

```text
ossd/            Python 包、生成器、传输与命令行
tests/           离线回归测试
pyproject.toml   包、依赖组、格式化、lint 与测试配置
uv.lock          锁定依赖
.python-version  开发 Python 版本
.github/         CI 工作流
docs/            概念、协议、操作流程和验证结论
assets/          用户自行提供的原厂资产（忽略提交）
tmp/             临时产物、历史夹具和旧实现（忽略提交）
```

- [开卡流程](docs/02-controller/sm2263xt/opening/card-opening-guide.md)
- [实际案例：SM2263XT + YMTC 开卡](docs/07-cases/sm2263xt-ymtc.md)
- [数据来源与主流程](docs/05-reference/design.md)
- [文档索引](docs/README.md)

# 量化交易与分析项目

## 概述

本项目旨在构建一个综合性的量化交易与分析平台，专注于中国A股市场。项目利用 Python 作为主要开发语言，并在 Windows 环境下进行开发和测试。

## 项目结构

根据当前目录结构，项目包含以下主要模块：

-   `analysis/`: 存放市场数据分析相关的脚本和结果。
-   `alerting/`: 可能包含交易信号或风险预警相关的模块。
-   `bin/`: 可能存放可执行文件或脚本。
-   `data/`: 用于存储原始或处理后的市场数据。
-   `decorators/`: 包含自定义的 Python 装饰器。
-   `excel/`: 可能用于处理或生成 Excel 文件。
-   `fetch/`: 负责从各种数据源（如 Tushare, Baostock）获取数据的脚本。
-   `file_checker/`: 可能包含用于检查文件完整性或格式的工具。
-   `filters/`: 用于数据筛选或信号过滤的模块。
-   `fonts/`: 存放项目可能使用的字体文件（例如，用于图表绘制）。
-   `images/`/`svg/`: 存放生成的图片或矢量图形文件。
-   `kline_charts/`: 专门用于生成 K 线图或其他技术图表的模块。
-   `labs/`: 用于实验性功能或代码测试的目录。
-   `roles/`: 存放使用 LangGPT 规范定义的 AI 角色 Prompt，例如：
    -   `meta_2.md`: LangGPT Prompt Architect 元角色。
    -   `python_trader_a_shares.md`: Python A股量化交易员角色。
-   `strategy/`: 核心目录，存放具体的量化交易策略代码。
-   `utils/`: 包含项目中可复用的工具函数或类。
-   `wordclouds/`: 用于生成词云图的脚本或结果。

## 主要文件

-   `main.py`: 项目的主入口文件或核心逻辑。
-   `test.py`: 用于单元测试或功能测试。
-   `config.ini`: 配置文件，可能包含 API密钥、数据库连接信息等。
-   `.gitignore`: 定义了 Git 版本控制忽略的文件和目录。
-   `README.md`: 本文件，提供项目概览。

## 环境与依赖

-   **语言**: Python
-   **操作系统**: Windows (主要开发环境)
-   **核心库 (可能)**: Pandas, NumPy, Matplotlib, Tushare, Baostock, vnpy, easytrader, backtrader, rqalpha, pytdx 等 (具体依赖请查看代码或 requirements.txt 文件)。

## 如何开始 (示例)

1.  克隆本项目。
2.  配置 `config.ini` 文件（如果需要）。
3.  安装所需的 Python 依赖库 (例如 `pip install -r requirements.txt` - 如果存在)。
4.  运行 `main.py` 或其他相关脚本。

## 贡献

欢迎对本项目进行贡献，可以通过提交 Issue 或 Pull Request 的方式参与。

## todo
- [x] 根据涨停原因对个股分组
- [x] 形态选股区分创业版
- [x] 根据分组叠加日内分时图
- [ ] 对非主板股同样获取每日复盘数据
- [ ] whimsical归类使用近义词
- [ ] 直观展示每日涨停梯队，非主板可以日内跳跃

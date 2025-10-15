### 通达信集合竞价自动截图器

- 入口：`automation/tdx_auction_screenshot.py`
- 依赖：`pyautogui`, `pillow`, `schedule`
- 运行环境：Windows + 通达信已启动且界面与校准一致

#### 安装
```bash
conda activate trading
pip install pyautogui pillow schedule
```

#### 首次校准（回车确认）
```bash
python automation/tdx_auction_screenshot.py calibrate
```
跟随提示依次：
1) 悬停到「封单额」表头，回车确认
2) 悬停到截图区域左上角，回车确认
3) 悬停到截图区域右下角，回车确认
生成 `config/tdx_screenshot.json`。

#### 启动定时截图（示例：09:15:30/09:20:30/09:25:30）
```bash
python automation/tdx_auction_screenshot.py start
```
脚本流程：激活通达信 → 键盘输入 `67`+回车跳转到“A股” → 点击「封单额」排序 → 按配置区域截图 → 自动最小化窗口。

#### 手动立即截图
```bash
python automation/tdx_auction_screenshot.py snap
```

- 截图保存：`data/screenshots/auction/YYYYMMDD_0915.png` 等
- 日志：`logs/tdx_screenshot.log`

注意：
- 若通达信分辨率、DPI 缩放或布局变化，需要重新 `calibrate`。
- 若排序方向不对，可将配置中的 `sort_click_count` 调整为 1 或 3。 
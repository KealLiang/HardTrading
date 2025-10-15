"""
通达信集合竞价自动截图器

用途：
- 在集合竞价三个时间点（09:15、09:20、09:25）自动完成以下动作：
  1) 激活通达信窗口
  2) 键盘输入“67”并回车跳转到「A股」
  3) 点击表头的「封单额」进行排序
  4) 截取配置区域，保存为图片
- 提供交互式「坐标与区域校准」工具（回车确认），一次校准长期复用

使用方法：
1) 先安装依赖（Windows 环境）：
   conda activate trading
   pip install pyautogui pillow schedule

2) 运行校准（只需首次或界面布局改变时）：
   python automation/tdx_auction_screenshot.py calibrate

   按提示依次悬停并按回车，生成配置文件 config/tdx_screenshot.json。

3) 启动定时器（建议在竞价前启动，09:15/09:20/09:25 自动截图）：
   python automation/tdx_auction_screenshot.py start

4) 手动立即截图（便于调试）：
   python automation/tdx_auction_screenshot.py snap

文件与目录：
- 配置：config/tdx_screenshot.json
- 截图：data/screenshots/auction/YYYYMMDD_0915.png 等
- 日志：logs/tdx_screenshot.log

作者：Trading System
创建时间：2025-10-15
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 第三方
import pyautogui as pag
import schedule

# 常量配置（可被配置文件覆盖）
DEFAULT_CONFIG = {
    "window_titles": [
        "通达信",  # 常见窗口标题包含关键词
        "金融终端",
        "行情",
    ],
    # 需要用户校准的坐标与区域
    "fengdan_header_point": [0, 0],       # 「封单额」表头点击坐标
    # 屏幕区域：left, top, width, height
    "screenshot_region": [0, 0, 0, 0],
    # 存储目录
    "save_dir": "data/screenshots/auction",
    # 截图前点击「封单额」次数（有的版本需点击两次才能降序）
    "sort_click_count": 2,
    # 时间点
    "auction_times": ["09:15:00", "09:20:00", "09:25:00"],
    # 执行期行为
    "use_block_input": True,               # 执行期间临时阻断用户鼠标/键盘输入
    "restore_mouse": True,                 # 执行后恢复鼠标位置
    "minimize_after_capture": True,        # 截图完成后最小化通达信
    # 键盘精灵快捷跳转
    "ak_shortcut": "67"                   # 跳转到『A股』的快捷键（输入后回车）
}

CONFIG_PATH = os.path.join("config", "tdx_screenshot.json")
LOG_PATH = os.path.join("logs", "tdx_screenshot.log")


class ConfigManager:
    """管理加载与保存截图配置。"""

    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.config = DEFAULT_CONFIG.copy()
        if os.path.exists(self.path):
            self.load()
        else:
            self.save()  # 生成模板文件

    def load(self) -> None:
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 合并默认值，确保新增字段有默认
        merged = DEFAULT_CONFIG.copy()
        merged.update(data or {})
        self.config = merged

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    # 便捷访问器
    def __getitem__(self, key: str):
        return self.config.get(key)

    def __setitem__(self, key: str, value):
        self.config[key] = value
        self.save()

    def get(self, key: str, default=None):
        """字典式读取，兼容 DEFAULT_CONFIG 默认值。"""
        return self.config.get(key, DEFAULT_CONFIG.get(key, default))


class TDXScreenshotter:
    """通达信截图执行器。"""

    def __init__(self, config: ConfigManager):
        self.cfg = config
        os.makedirs(self.cfg["save_dir"], exist_ok=True)
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(LOG_PATH, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
        self._current_window = None

    # --------- 窗口与交互 ---------
    def _find_tdx_window(self):
        """通过标题关键词查找通达信窗口。"""
        try:
            for title_kw in self.cfg["window_titles"]:
                windows = pag.getWindowsWithTitle(title_kw)
                if windows:
                    # 选择最前面的一个
                    return windows[0]
        except Exception:
            # 某些平台可能不支持 getWindowsWithTitle
            return None
        return None

    def activate_tdx(self) -> bool:
        win = self._find_tdx_window()
        if not win:
            self.logger.error("未找到通达信窗口，请确认通达信已启动并可见")
            return False
        try:
            win.activate()
            time.sleep(0.5)
            win.maximize()
            time.sleep(0.3)
            self._current_window = win
            return True
        except Exception as e:
            self.logger.error(f"激活通达信窗口失败: {e}")
            return False

    def _safe_click(self, point: Tuple[int, int], description: str, clicks: int = 1) -> None:
        x, y = point
        if x == 0 and y == 0:
            self.logger.warning(f"{description} 坐标未校准，跳过点击")
            return
        pag.moveTo(x, y, duration=0.2)
        pag.click(clicks=clicks, interval=0.1)
        time.sleep(0.2)

    # --------- 核心流程 ---------
    def prepare_view(self) -> None:
        """激活窗口 -> 键盘跳转到A股 -> 点击封单额排序。"""
        if not self.activate_tdx():
            return
        # 直接使用键盘精灵跳转，不再依赖 A股 坐标
        try:
            shortcut = str(self.cfg.get("ak_shortcut", "67"))
            if shortcut:
                pag.typewrite(shortcut, interval=0.05)
                pag.press('enter')
                time.sleep(0.2)
        except Exception:
            pass
        # 多次点击确保按降序排列
        self._safe_click(tuple(self.cfg["fengdan_header_point"]), "封单额表头", clicks=max(1, int(self.cfg.get("sort_click_count", 2))) )

    def take_screenshot(self, time_tag: Optional[str] = None) -> Optional[str]:
        """根据配置区域截图，返回保存路径。"""
        region = tuple(self.cfg["screenshot_region"])  # (left, top, width, height)
        if len(region) != 4 or sum(region) == 0:
            self.logger.error("截图区域未校准，请先运行 calibrate")
            return None

        today = datetime.now().strftime('%Y%m%d')
        tag = time_tag or datetime.now().strftime('%H%M')
        filename = f"{today}_{tag}.png"
        save_path = os.path.join(self.cfg["save_dir"], filename)

        image = pag.screenshot(region=region)
        image.save(save_path)
        self.logger.info(f"截图完成: {save_path}")
        return save_path

    def run_once(self, time_point: Optional[str] = None) -> None:
        """执行一次完整流程：激活 -> 点击 -> 截图。"""
        tag = (time_point or datetime.now().strftime('%H:%M:%S')).replace(':', '')[:4]
        self.logger.info(f"开始 {tag} 截图流程...")

        original_pos = pag.position()
        use_block = bool(self.cfg.get("use_block_input", True))

        def _block_input(enable: bool) -> None:
            if not enable:
                return
            try:
                import ctypes
                ctypes.windll.user32.BlockInput(True)
            except Exception:
                # 非管理员或不支持时忽略
                pass

        def _unblock_input() -> None:
            if not use_block:
                return
            try:
                import ctypes
                ctypes.windll.user32.BlockInput(False)
            except Exception:
                pass

        try:
            _block_input(use_block)
            self.prepare_view()
            path = self.take_screenshot(tag)
        finally:
            _unblock_input()
            if self.cfg.get("restore_mouse", True):
                try:
                    pag.moveTo(original_pos[0], original_pos[1], duration=0)
                except Exception:
                    pass

        if self.cfg.get("minimize_after_capture", True):
            try:
                win = self._current_window or self._find_tdx_window()
                if win:
                    win.minimize()
            except Exception as e:
                self.logger.warning(f"最小化通达信窗口失败: {e}")

        if path:
            self.logger.info(f"{tag} 截图完成")
        else:
            self.logger.warning(f"{tag} 截图失败")


class TDXAuctionScreenshotScheduler:
    """定时调度器：在竞价三个时间点自动截图。"""

    def __init__(self, shooter: TDXScreenshotter):
        self.shooter = shooter
        self.auction_times: List[str] = self.shooter.cfg["auction_times"]
        self.is_running = False

    def schedule_daily(self) -> None:
        schedule.clear()
        for t in self.auction_times:
            schedule.every().day.at(t).do(self.shooter.run_once, t)
            logging.info(f"已设置定时截图: {t}")

    def start(self) -> None:
        self.schedule_daily()
        self.is_running = True
        logging.info("🚀 通达信集合竞价自动截图器已启动")
        for t in self.auction_times:
            logging.info(f"  📅 {t} 自动截图")
        try:
            while self.is_running:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        self.is_running = False
        schedule.clear()
        logging.info("截图调度器已停止")


# --------- 校准工具 ---------

def interactive_calibrate(cfg: ConfigManager) -> None:
    print("将进行交互式校准，请先确保通达信窗口位于目标界面上。")
    print("操作：把鼠标移动到提示位置后，回到控制台按回车确认。\n")

    time.sleep(1)

    # 封单额表头
    input("1/3) 请把鼠标悬停到表头『封单额』位置，然后按回车...")
    x, y = pag.position()
    cfg["fengdan_header_point"] = [x, y]
    print(f"已记录 封单额 表头坐标: ({x}, {y})")

    # 区域：左上
    input("2/3) 请把鼠标悬停到需要截图区域的『左上角』，按回车...")
    left, top = pag.position()

    # 区域：右下
    input("3/3) 请把鼠标悬停到需要截图区域的『右下角』，按回车...")
    right, bottom = pag.position()

    width = max(0, right - left)
    height = max(0, bottom - top)
    cfg["screenshot_region"] = [left, top, width, height]
    cfg.save()

    print("校准完成，已保存到:", CONFIG_PATH)


def main():
    cfg = ConfigManager()
    shooter = TDXScreenshotter(cfg)

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd in ("start", "run", "scheduler"):
            scheduler = TDXAuctionScreenshotScheduler(shooter)
            scheduler.start()
        elif cmd in ("snap", "shot", "once"):
            shooter.run_once()
        elif cmd in ("calibrate", "config"):
            interactive_calibrate(cfg)
        elif cmd == "status":
            next_run = schedule.next_run() if schedule.jobs else None
            print("调度器状态：")
            print("  运行中: 否 (仅查询状态，未启动)")
            print("  计划时间:", ", ".join(cfg["auction_times"]))
            print("  下次运行:", next_run)
        else:
            print(f"未知命令: {cmd}")
            print("可用命令: start | snap | calibrate | status")
    else:
        # 默认启动调度器
        scheduler = TDXAuctionScreenshotScheduler(shooter)
        scheduler.start()


if __name__ == "__main__":
    main() 
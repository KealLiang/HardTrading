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
   或者在 PyCharm 中直接右键运行此脚本（默认就是 start 命令）

4) 手动立即截图（便于调试）：
   python automation/tdx_auction_screenshot.py snap

5) 使用自定义配置文件：
   python automation/tdx_auction_screenshot.py --config /path/to/config.json start

文件与目录：
- 配置：config/tdx_screenshot.json
- 截图：data/screenshots/auction/YYYYMMDD_0915.png 等
- 日志：logs/tdx_screenshot.log

特性：
- ✅ 自动定位项目根目录，支持在任意目录下运行
- ✅ 支持 PyCharm 直接点击运行（无需命令行参数）
- ✅ 支持自定义配置文件路径

作者：Trading System
创建时间：2025-10-15
更新时间：2025-10-21
"""

import argparse
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# 第三方
import pyautogui as pag
import schedule
from PIL import Image


# ========== 路径自动定位 ==========
def get_project_root() -> Path:
    """获取项目根目录（脚本所在目录的父目录）"""
    return Path(__file__).resolve().parent.parent


# 项目根目录
PROJECT_ROOT = get_project_root()

# 常量配置（可被配置文件覆盖）
DEFAULT_CONFIG = {
    "window_titles": [
        "通达信",  # 常见窗口标题包含关键词
        "金融终端",
        "行情",
    ],
    # 需要用户校准的坐标与区域
    "fengdan_header_point": [0, 0],  # 「封单额」表头点击坐标
    # 屏幕区域：left, top, width, height
    "screenshot_region": [0, 0, 0, 0],
    # 存储目录
    "save_dir": "data/screenshots/auction",
    # 截图前点击「封单额」次数（有的版本需点击两次才能降序）
    "sort_click_count": 2,
    # 时间点
    "auction_times": ["09:15:00", "09:20:00", "09:25:00"],
    # 执行期行为
    "use_block_input": True,  # 执行期间临时阻断用户鼠标/键盘输入
    "restore_mouse": True,  # 执行后恢复鼠标位置
    "minimize_after_capture": True,  # 截图完成后最小化通达信
    # 键盘精灵快捷跳转
    "ak_shortcut": "67",  # 跳转到『A股』的快捷键（输入后回车）
    # 截图压缩
    "image_format": "webp",  # webp | jpeg | png
    "jpeg_quality": 35,  # 0-95，越低越小
    "webp_quality": 30,  # 0-100，越低越小
    "webp_method": 6,  # 0-6，越高越慢体积越小
    "png_optimize": True,  # PNG 优化
    "downscale_ratio": 1.0,  # 可选缩放比例（例如 0.8 可进一步减小体积）
    "convert_to_grayscale": False  # 将图片转为灰度，显著压缩体积
}

# 使用绝对路径，基于项目根目录
CONFIG_PATH = str(PROJECT_ROOT / "config" / "tdx_screenshot.json")
LOG_PATH = str(PROJECT_ROOT / "logs" / "tdx_screenshot.log")


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
        # 确保 save_dir 使用绝对路径
        save_dir = self.cfg["save_dir"]
        if not os.path.isabs(save_dir):
            save_dir = str(PROJECT_ROOT / save_dir)
        os.makedirs(save_dir, exist_ok=True)
        self.cfg.config["save_dir"] = save_dir  # 更新为绝对路径
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
        self._safe_click(tuple(self.cfg["fengdan_header_point"]), "封单额表头",
                         clicks=max(1, int(self.cfg.get("sort_click_count", 2))))

    def take_screenshot(self, time_tag: Optional[str] = None) -> Optional[str]:
        """根据配置区域截图，返回保存路径。"""
        region = tuple(self.cfg["screenshot_region"])  # (left, top, width, height)
        if len(region) != 4 or sum(region) == 0:
            self.logger.error("截图区域未校准，请先运行 calibrate")
            return None

        today = datetime.now().strftime('%Y%m%d')
        tag = time_tag or datetime.now().strftime('%H%M')

        fmt = str(self.cfg.get("image_format", "webp")).lower()
        ext_map = {"jpeg": "jpg", "jpg": "jpg", "webp": "webp", "png": "png"}
        ext = ext_map.get(fmt, "webp")
        filename = f"{today}_{tag}.{ext}"
        save_path = os.path.join(self.cfg["save_dir"], filename)

        image = pag.screenshot(region=region)

        # 可选缩放，进一步减小文件体积
        try:
            ratio = float(self.cfg.get("downscale_ratio", 1.0))
        except Exception:
            ratio = 1.0
        if ratio and ratio < 1.0:
            w, h = image.size
            new_w = max(1, int(w * ratio))
            new_h = max(1, int(h * ratio))
            image = image.resize((new_w, new_h), resample=Image.LANCZOS)

        # 保存时按格式压缩
        try:
            if fmt in ("jpeg", "jpg"):
                params = {
                    "quality": int(self.cfg.get("jpeg_quality", 35)),
                    "optimize": True,
                    "progressive": True,
                    "subsampling": "4:2:0",
                }
                if bool(self.cfg.get("convert_to_grayscale", False)):
                    # 灰度模式体积更小，适合以文本为主的截图
                    if image.mode != "L":
                        image = image.convert("L")
                else:
                    if image.mode in ("RGBA", "P"):
                        image = image.convert("RGB")
                image.save(save_path, format="JPEG", **params)
            elif fmt == "png":
                params = {
                    "optimize": bool(self.cfg.get("png_optimize", True)),
                    "compress_level": 9,
                }
                image.save(save_path, format="PNG", **params)
            else:  # webp 默认
                params = {
                    "quality": int(self.cfg.get("webp_quality", 30)),
                    "method": int(self.cfg.get("webp_method", 6)),
                }
                image.save(save_path, format="WEBP", **params)
        except Exception as e:
            # 回退为 PNG 保存，避免因格式不支持导致丢图
            fallback_path = os.path.splitext(save_path)[0] + ".png"
            image.save(fallback_path, format="PNG", optimize=True, compress_level=9)
            self.logger.warning(f"图片保存失败，已回退为 PNG：{fallback_path}，错误：{e}")
            return fallback_path

        try:
            size_kb = os.path.getsize(save_path) / 1024.0
            self.logger.info(f"截图完成: {save_path} ({size_kb:.1f} KB)")
        except Exception:
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
        self.completed_times = set()  # 记录已完成的时间点

    def _run_and_track(self, time_point: str) -> None:
        """执行截图并记录完成状态"""
        self.shooter.run_once(time_point)
        self.completed_times.add(time_point)
        logging.info(f"已完成 {len(self.completed_times)}/{len(self.auction_times)} 个时间点")
        
        # 检查是否所有任务都已完成
        if len(self.completed_times) >= len(self.auction_times):
            logging.info("✅ 所有截图任务已完成，程序将自动停止")
            self.is_running = False

    def schedule_daily(self) -> None:
        schedule.clear()
        for t in self.auction_times:
            schedule.every().day.at(t).do(self._run_and_track, t)
            logging.info(f"已设置定时截图: {t}")

    def start(self) -> None:
        self.schedule_daily()
        self.is_running = True
        self.completed_times.clear()  # 清空已完成记录
        logging.info("🚀 通达信集合竞价自动截图器已启动")
        for t in self.auction_times:
            logging.info(f"  📅 {t} 自动截图")
        logging.info("💡 完成所有时间点后将自动停止")
        try:
            while self.is_running:
                schedule.run_pending()
                time.sleep(1)
            # 正常完成所有任务后的停止
            self.stop()
        except KeyboardInterrupt:
            logging.info("⚠️ 用户手动中断")
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


def run_auto():
    parser = argparse.ArgumentParser(
        description="通达信集合竞价自动截图器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python automation/tdx_auction_screenshot.py start              # 启动定时截图
  python automation/tdx_auction_screenshot.py snap               # 立即截图一次
  python automation/tdx_auction_screenshot.py calibrate          # 校准坐标
  python automation/tdx_auction_screenshot.py --config custom.json start  # 使用自定义配置
        """
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="start",
        choices=["start", "run", "scheduler", "snap", "shot", "once", "calibrate", "config", "status"],
        help="执行命令 (默认: start)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=CONFIG_PATH,
        help=f"配置文件路径 (默认: {CONFIG_PATH})"
    )

    args = parser.parse_args()

    # 加载配置
    cfg = ConfigManager(args.config)
    shooter = TDXScreenshotter(cfg)

    cmd = args.command.lower()
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
        print("  配置文件:", args.config)
        print("  项目根目录:", PROJECT_ROOT)


if __name__ == "__main__":
    run_auto()

import os
import time
import datetime
import schedule
import pyautogui
import pygetwindow as gw

# --- 用户配置区 ---
# 请根据您的实际情况修改以下变量

# 1. 通达信主窗口的标题 (请根据您软件的实际标题填写)
WINDOW_TITLE = "通达信金融终端"

# 2. 截图保存的目录 (脚本会在项目根目录下创建此文件夹)
SAVE_DIRECTORY = "bidding_captures"

# 3. 操作坐标 (这是最关键的一步, 需要您手动获取)
#
#    如何获取坐标?
#    a. 激活您的虚拟环境: .venv-3.11\Scripts\activate
#    b. 运行 python 进入交互模式
#    c. 输入 import pyautogui
#    d. 输入 pyautogui.mouseInfo()
#    e. 将鼠标移动到屏幕上的目标位置, 交互窗口会实时显示 X, Y 坐标和 RGB 颜色
#
#    请将获取到的坐标填写到下方. 如果某个操作不需要(例如窗口默认就是最大化), 可以将其设置为 None.

# 示例坐标 (请务必替换成您自己的坐标!)
SORT_BUTTON_COORDS = (123, 456)      # "封单额" 排序按钮的屏幕 X, Y 坐标
CAPTURE_REGION = (100, 200, 800, 600) # 需要截图的区域 (左上角X, 左上角Y, 宽度, 高度)
MAX_PAGES = 10 # 为防止意外情况导致无限翻页, 设定一个最大翻页次数


def take_snapshot():
    """
    找到通达信窗口, 点击排序并截图.
    """
    print(f"[{datetime.datetime.now()}] 开始执行截图任务...")

    try:
        # 查找窗口
        win_list = gw.getWindowsWithTitle(WINDOW_TITLE)
        if not win_list:
            print(f"错误: 未找到标题为 '{WINDOW_TITLE}' 的窗口. 请检查标题是否正确或软件是否已打开.")
            return

        win = win_list[0]

        # 激活并最大化窗口
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(0.5) # 等待窗口激活
        win.maximize()
        time.sleep(1) # 等待窗口最大化动画

        # --- 模拟鼠标操作 ---
        # 如果需要点击排序按钮
        if SORT_BUTTON_COORDS:
            print(f"移动到排序按钮并点击: {SORT_BUTTON_COORDS}")
            pyautogui.moveTo(SORT_BUTTON_COORDS[0], SORT_BUTTON_COORDS[1], duration=0.5)
            pyautogui.click()
            time.sleep(1) # 等待排序完成

        # --- 截图 (支持多页) ---
        if CAPTURE_REGION:
            print(f"在区域 {CAPTURE_REGION} 进行截图...")
            # 创建保存目录
            if not os.path.exists(SAVE_DIRECTORY):
                os.makedirs(SAVE_DIRECTORY)

            # --- 循环翻页截图 ---
            previous_screenshot = None
            for page_num in range(1, MAX_PAGES + 1):
                # 执行截图
                current_screenshot = pyautogui.screenshot(region=CAPTURE_REGION)

                # 和上一张图比较, 如果一样说明到底了
                if previous_screenshot:
                    if list(current_screenshot.getdata()) == list(previous_screenshot.getdata()):
                        print("检测到最后一页, 截图完成.")
                        break
                
                # 生成文件名并保存
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                filename = os.path.join(SAVE_DIRECTORY, f"snapshot_{timestamp}_p{page_num}.png")
                current_screenshot.save(filename)
                print(f"成功! 第 {page_num} 页截图已保存至: {filename}")

                # 准备下一轮
                previous_screenshot = current_screenshot
                pyautogui.press('pagedown')
                time.sleep(0.5) # 等待翻页动画
            else:
                 print(f"警告: 已达到最大截图页数 {MAX_PAGES}, 自动停止.")

        else:
            print("错误: 未配置截图区域 (CAPTURE_REGION).")

    except Exception as e:
        print(f"执行截图时发生错误: {e}")

def main():
    """
    主函数, 设置定时任务.
    """
    print("自动化截图脚本已启动...")
    print(f"将在每天的 09:15, 09:20, 09:30 执行截图.")
    print("请保持此脚本运行, 不要关闭窗口.")

    # 设置定时任务
    schedule.every().day.at("09:15").do(take_snapshot)
    schedule.every().day.at("09:20").do(take_snapshot)
    schedule.every().day.at("09:30").do(take_snapshot)
    
    # schedule.every(10).seconds.do(take_snapshot) # 用于测试, 每10秒执行一次

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    # 在运行前, 请确认您已经根据脚本顶部的注释配置好了坐标!
    # 首次运行建议先使用测试任务(每10秒一次)来验证坐标是否正确.
    main() 
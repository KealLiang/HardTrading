import logging
import os
import sys
import platform
import requests
import zipfile
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

def get_chrome_version():
    """
    获取本地Chrome浏览器版本
    
    :return: Chrome版本号或None
    """
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
            version, _ = winreg.QueryValueEx(key, "version")
            return version
        elif system == "Darwin":  # macOS
            import subprocess
            process = subprocess.Popen(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"], stdout=subprocess.PIPE)
            version = process.communicate()[0].decode("UTF-8").replace("Google Chrome", "").strip()
            return version
        elif system == "Linux":
            import subprocess
            process = subprocess.Popen(["google-chrome", "--version"], stdout=subprocess.PIPE)
            version = process.communicate()[0].decode("UTF-8").replace("Google Chrome", "").strip()
            return version
    except Exception as e:
        logging.error(f"获取Chrome版本失败: {str(e)}")
    return None

def print_chromedriver_help():
    """
    打印ChromeDriver下载帮助信息
    
    :return: 帮助信息字符串
    """
    chrome_version = get_chrome_version()
    version_msg = f"检测到的Chrome版本: {chrome_version}" if chrome_version else "无法检测Chrome版本，请手动确认您的Chrome版本"
    
    help_msg = f"""
=== ChromeDriver下载帮助 ===
{version_msg}

请按照以下步骤手动下载并安装ChromeDriver:

1. 访问 https://chromedriver.chromium.org/downloads
2. 下载与您Chrome浏览器版本匹配的ChromeDriver
   (例如Chrome版本为 115.x.xxxx.xx，则下载ChromeDriver 115.x.xxxx.xx)
3. 解压下载的文件，得到chromedriver.exe (Windows)或chromedriver (Mac/Linux)
4. 将chromedriver放置在以下任一位置:
   - {os.path.join(os.path.dirname(os.path.abspath(__file__)), "chromedriver.exe")}
   - {os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "driver\\chromedriver.exe")}
   - {os.path.join(os.environ.get("USERPROFILE", ""), "Downloads")} (Windows)
   - /usr/local/bin/ (Mac/Linux)

下载完成后，请重新运行程序。
"""
    logging.info(help_msg)
    print(help_msg)
    return help_msg

def download_chromedriver(chrome_version=None):
    """
    根据Chrome版本下载对应的ChromeDriver
    
    :param chrome_version: Chrome版本号，如果为None则自动检测
    :return: 下载的ChromeDriver路径或None
    """
    if not chrome_version:
        chrome_version = get_chrome_version()
        
    if not chrome_version:
        logging.error("无法检测Chrome版本，无法自动下载ChromeDriver")
        return None
        
    # 提取主版本号
    major_version = chrome_version.split('.')[0]
    
    try:
        # 确定下载目录
        download_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 确定操作系统和文件名
        system = platform.system()
        if system == "Windows":
            platform_name = "win32"
            driver_name = "chromedriver.exe"
        elif system == "Darwin":  # macOS
            if platform.machine() == "arm64":
                platform_name = "mac-arm64"
            else:
                platform_name = "mac-x64"
            driver_name = "chromedriver"
        elif system == "Linux":
            if platform.machine() == "aarch64":
                platform_name = "linux-arm64"
            else:
                platform_name = "linux64"
            driver_name = "chromedriver"
        else:
            logging.error(f"不支持的操作系统: {system}")
            return None
            
        # 构建下载URL
        base_url = f"https://chromedriver.storage.googleapis.com"
        
        # 尝试获取匹配版本的ChromeDriver
        try:
            # 首先尝试完全匹配版本
            version_url = f"{base_url}/LATEST_RELEASE_{chrome_version}"
            response = requests.get(version_url, timeout=10)
            if response.status_code != 200:
                # 尝试匹配主版本号
                version_url = f"{base_url}/LATEST_RELEASE_{major_version}"
                response = requests.get(version_url, timeout=10)
                
            if response.status_code == 200:
                driver_version = response.text.strip()
                logging.info(f"找到匹配的ChromeDriver版本: {driver_version}")
            else:
                logging.warning(f"无法获取匹配的ChromeDriver版本，使用备选方法")
                # 使用备选方法 - 直接使用Chrome版本
                driver_version = major_version
        except Exception as e:
            logging.warning(f"获取ChromeDriver版本失败: {str(e)}，使用Chrome主版本: {major_version}")
            driver_version = major_version
            
        # 构建下载URL
        download_url = f"{base_url}/{driver_version}/chromedriver_{platform_name}.zip"
        logging.info(f"开始下载ChromeDriver: {download_url}")
        
        # 下载文件
        response = requests.get(download_url, stream=True, timeout=30)
        if response.status_code != 200:
            logging.error(f"下载ChromeDriver失败，状态码: {response.status_code}")
            return None
            
        # 保存zip文件
        zip_path = os.path.join(download_dir, "chromedriver.zip")
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        # 解压文件
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(download_dir)
            
        # 获取ChromeDriver路径
        driver_path = os.path.join(download_dir, driver_name)
        
        # 设置可执行权限（仅Linux/Mac需要）
        if system != "Windows" and os.path.exists(driver_path):
            os.chmod(driver_path, 0o755)
            
        # 删除zip文件
        os.remove(zip_path)
        
        logging.info(f"成功下载并解压ChromeDriver到: {driver_path}")
        return driver_path
        
    except Exception as e:
        logging.error(f"下载ChromeDriver时出错: {str(e)}")
        return None

# 在setup_chrome_browser函数中添加更多反检测选项
def setup_chrome_browser(headless=False):
    options = Options()
    if headless:
        options.add_argument("--headless")
    
    # 现有选项
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # 新增反检测选项
    options.add_argument("--disable-web-security")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-extensions")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")
    
    # 设置用户代理
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = None
    wait = None
    
    try:
        # 尝试使用离线模式，避免网络问题
        try:
            # 首先尝试直接使用Chrome浏览器
            driver = webdriver.Chrome(options=options)
            logging.info("成功使用系统默认Chrome浏览器")
        except Exception as e1:
            logging.warning(f"使用系统默认Chrome浏览器失败: {str(e1)}，尝试其他方法")
            
            # 尝试查找本地已安装的ChromeDriver
            try:
                # 检查常见的ChromeDriver位置
                possible_paths = [
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "chromedriver.exe"),
                    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "driver\\chromedriver.exe"),
                    "C:\\Program Files\\Google\\Chrome\\Application\\chromedriver.exe",
                    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chromedriver.exe",
                    os.path.join(os.environ.get("USERPROFILE", ""), "Downloads\\chromedriver.exe"),
                ]
                
                # 针对非Windows系统添加额外路径
                if platform.system() != "Windows":
                    possible_paths.extend([
                        "/usr/local/bin/chromedriver",
                        "/usr/bin/chromedriver",
                        os.path.expanduser("~/chromedriver")
                    ])
                
                driver_found = False
                for driver_path in possible_paths:
                    if os.path.exists(driver_path):
                        logging.info(f"找到本地ChromeDriver: {driver_path}")
                        try:
                            driver = webdriver.Chrome(service=Service(driver_path), options=options)
                            driver_found = True
                            break
                        except Exception as e:
                            logging.warning(f"使用本地ChromeDriver失败: {str(e)}")
                
                # 如果没有找到可用的ChromeDriver，尝试自动下载
                if not driver_found:
                    logging.info("尝试自动下载ChromeDriver")
                    driver_path = download_chromedriver()
                    if driver_path and os.path.exists(driver_path):
                        try:
                            driver = webdriver.Chrome(service=Service(driver_path), options=options)
                            driver_found = True
                        except Exception as e:
                            logging.warning(f"使用下载的ChromeDriver失败: {str(e)}")
                
                # 如果仍然没有找到，尝试使用webdriver_manager但设置离线模式
                if not driver_found:
                    logging.info("尝试使用ChromeDriverManager，设置离线模式")
                    os.environ['WDM_LOCAL_ONLY'] = '1'  # 设置为仅使用本地缓存
                    driver = webdriver.Chrome(service=Service(ChromeDriverManager(cache_valid_range=365).install()), options=options)
            except Exception as e2:
                logging.error(f"所有ChromeDriver尝试均失败: {str(e2)}")
                # 打印帮助信息
                print_chromedriver_help()
                return None, None
        
        # 执行反自动化检测的JavaScript
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            """
        })
        
        # 设置等待
        from selenium.webdriver.support.ui import WebDriverWait
        wait = WebDriverWait(driver, 10)
        return driver, wait
    except Exception as e:
        logging.error(f"浏览器设置失败: {str(e)}")
        if driver:
            try:
                driver.quit()
            except:
                pass
        return None, None

def close_browser(driver):
    """
    安全关闭浏览器
    
    :param driver: WebDriver实例
    """
    if driver:
        try:
            driver.quit()
        except Exception as e:
            logging.error(f"关闭浏览器时出错: {str(e)}")
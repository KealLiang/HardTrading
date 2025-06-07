import logging
import time
import random
import io
import base64
import os
import numpy as np
from PIL import Image
import ddddocr
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# 导入WebDriver工具模块
from utils.webdriver_util import setup_chrome_browser, close_browser

class SimpleCaptchaSolver:
    """
    简化的东方财富网验证码求解器
    基于ddddocr实现，专注于解决东方财富网的滑动验证码
    """
    
    def __init__(self, max_retry=3, headless=True):
        """
        初始化验证码求解器
        
        :param max_retry: 最大重试次数
        :param headless: 是否使用无头模式
        """
        self.max_retry = max_retry
        self.headless = headless
        self.driver = None
        self.wait = None
        # 初始化ddddocr
        self.ocr = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
        
    def setup_browser(self):
        """设置浏览器环境"""
        self.driver, self.wait = setup_chrome_browser(headless=self.headless)
        if self.driver:
            # 设置页面加载超时
            self.driver.set_page_load_timeout(30)
            # 设置隐式等待
            self.driver.implicitly_wait(10)
        return self.driver is not None
        
    def solve_captcha(self, url):
        """
        解决指定URL的滑动验证码
        
        :param url: 验证码页面URL
        :return: 是否成功
        """
        if not self.driver and not self.setup_browser():
            logging.error("无法设置浏览器，验证码解决失败")
            return False
            
        try:
            logging.info(f"正在访问验证页面: {url}")
            self.driver.get(url)
            
            # 等待页面完全加载
            time.sleep(3)
            
            # 尝试关闭东方财富网的弹窗
            self._close_eastmoney_popup()
            
            # 检查是否需要验证码
            if not self._has_captcha():
                logging.info("页面无需验证码")
                return True
            
            # 尝试解决验证码
            return self._solve_slide_captcha()
            
        except Exception as e:
            logging.error(f"验证码解决过程中出错: {str(e)}")
            return False
    
    def _close_eastmoney_popup(self):
        """关闭东方财富网的广告弹窗"""
        try:
            # 等待弹窗出现
            time.sleep(1)
            
            # 尝试方法1：通过图片URL定位关闭按钮
            try:
                close_btn = self.driver.find_element(By.CSS_SELECTOR, "img[src*='ic_close.png']")
                if close_btn and close_btn.is_displayed():
                    logging.info("找到关闭按钮(通过图片URL)")
                    close_btn.click()
                    time.sleep(1)
                    return
            except:
                pass
                
            # 尝试方法2：通过样式定位关闭按钮
            try:
                close_elements = self.driver.find_elements(By.CSS_SELECTOR, "img[style*='position: absolute'][style*='cursor: pointer']")
                for element in close_elements:
                    if element.is_displayed():
                        logging.info("找到关闭按钮(通过样式)")
                        element.click()
                        time.sleep(1)
                        return
            except:
                pass
                
            # 尝试方法3：通过onclick属性
            try:
                close_elements = self.driver.find_elements(By.CSS_SELECTOR, "[onclick*='zoomin']")
                for element in close_elements:
                    if element.is_displayed():
                        logging.info("找到关闭按钮(通过onclick)")
                        element.click()
                        time.sleep(1)
                        return
            except:
                pass
                
            # 尝试方法4：通过文本内容
            try:
                close_elements = self.driver.find_elements(By.XPATH, "//*[text()='关闭']")
                for element in close_elements:
                    if element.is_displayed():
                        logging.info("找到关闭按钮(通过文本)")
                        element.click()
                        time.sleep(1)
                        return
            except:
                pass
                
            logging.info("没有找到需要关闭的弹窗或已自动关闭")
            
        except Exception as e:
            logging.warning(f"关闭弹窗时出错: {str(e)}")
    
    def _has_captcha(self):
        """
        检查页面是否有验证码
        """
        try:
            # 检查常见的验证码标识
            captcha_indicators = [
                "验证", "captcha", "verify", "滑动", "拖动",
                "请完成安全验证", "请拖动滑块"
            ]
            
            page_source = self.driver.page_source.lower()
            for indicator in captcha_indicators:
                if indicator.lower() in page_source:
                    return True
            
            # 检查是否有验证码相关元素
            captcha_selectors = [
                "[class*='captcha']",
                "[class*='verify']", 
                "[id*='captcha']",
                "[id*='verify']",
                "iframe[src*='captcha']",
                "iframe[src*='verify']"
            ]
            
            for selector in captcha_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        return True
                except:
                    continue
                    
            return False
            
        except Exception as e:
            logging.error(f"检查验证码时出错: {str(e)}")
            return False
    
    def _solve_slide_captcha(self):
        """
        解决滑动验证码
        """
        try:
            # 首先尝试处理iframe中的验证码
            if self._solve_iframe_captcha():
                return True
            
            # 然后尝试处理页面中的验证码
            if self._solve_page_captcha():
                return True
                
            # 最后尝试通用方法
            return self._solve_generic_captcha()
            
        except Exception as e:
            logging.error(f"解决滑动验证码时出错: {str(e)}")
            return False
    
    def _solve_iframe_captcha(self):
        """
        解决iframe中的验证码
        """
        try:
            # 查找验证码iframe
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            
            for iframe in iframes:
                try:
                    iframe_src = iframe.get_attribute("src") or ""
                    if any(keyword in iframe_src.lower() for keyword in ["captcha", "verify"]):
                        logging.info("找到验证码iframe")
                        
                        # 切换到iframe
                        self.driver.switch_to.frame(iframe)
                        
                        # 尝试解决验证码
                        if self._solve_captcha_in_current_frame():
                            self.driver.switch_to.default_content()
                            return True
                        
                        # 切换回主框架
                        self.driver.switch_to.default_content()
                        
                except Exception as e:
                    logging.warning(f"处理iframe时出错: {str(e)}")
                    try:
                        self.driver.switch_to.default_content()
                    except:
                        pass
                    continue
            
            return False
            
        except Exception as e:
            logging.error(f"解决iframe验证码时出错: {str(e)}")
            return False
    
    def _solve_page_captcha(self):
        """
        解决页面中的验证码
        """
        try:
            return self._solve_captcha_in_current_frame()
        except Exception as e:
            logging.error(f"解决页面验证码时出错: {str(e)}")
            return False
    
    def _solve_captcha_in_current_frame(self):
        """
        在当前框架中解决验证码
        """
        try:
            # 等待验证码加载
            time.sleep(2)
            
            # 使用确切的CSS选择器查找滑块元素
            try:
                # 查找滑块 - 使用提供的确切CSS选择器
                slider = self.driver.find_element(By.CSS_SELECTOR, ".em_slider_knob.em_show")
                if slider and slider.is_displayed():
                    logging.info("找到滑块元素: .em_slider_knob.em_show")
                    
                    # 先点击滑块激活验证码
                    logging.info("点击滑块激活验证码...")
                    ActionChains(self.driver).move_to_element(slider).click().perform()
                    time.sleep(2)  # 等待验证码图片加载
            except Exception as e:
                logging.warning(f"尝试点击滑块时出错: {str(e)}")
                
                # 尝试查找刷新按钮并点击，可能会重新加载验证码
                try:
                    refresh_btn = self.driver.find_element(By.CSS_SELECTOR, ".em_refresh_button")
                    if refresh_btn and refresh_btn.is_displayed():
                        logging.info("找到刷新按钮并点击")
                        refresh_btn.click()
                        time.sleep(2)  # 等待验证码重新加载
                except Exception as e2:
                    logging.warning(f"查找刷新按钮时出错: {str(e2)}")
            
            # 截取整个页面
            screenshot = self.driver.get_screenshot_as_png()
            img = Image.open(io.BytesIO(screenshot))
            
            # 转换为字节流供ddddocr使用
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='PNG')
            img_bytes = img_bytes.getvalue()
            
            # 使用ddddocr检测滑动距离
            try:
                # 尝试滑块匹配
                result = self.ocr.slide_match(img_bytes, img_bytes)
                if isinstance(result, dict) and 'target' in result:
                    distance = result['target'][0]
                elif isinstance(result, (int, float)):
                    distance = result
                else:
                    # 如果ddddocr无法识别，使用估算值
                    distance = img.width * 0.3  # 估算滑动距离为图片宽度的30%
                
                logging.info(f"检测到滑动距离: {distance}像素")
                
            except Exception as e:
                logging.warning(f"ddddocr检测失败: {str(e)}，使用估算距离")
                distance = img.width * 0.3
            
            # 再次查找滑块并执行滑动
            return self._perform_slide_with_exact_selectors(distance)
            
        except Exception as e:
            logging.error(f"在当前框架中解决验证码时出错: {str(e)}")
            return False
    
    def _perform_slide_with_exact_selectors(self, distance):
        """
        使用确切的CSS选择器查找滑块并执行滑动
        """
        try:
            # 查找滑块元素，使用确切的CSS选择器
            slider = None
            
            try:
                # 首先尝试使用东方财富网特定的CSS选择器
                slider = self.driver.find_element(By.CSS_SELECTOR, ".em_slider_knob.em_show")
                if slider and slider.is_displayed():
                    logging.info("找到滑块元素: .em_slider_knob.em_show")
            except:
                # 如果无法找到，尝试其他选择器
                logging.warning("无法找到准确的滑块元素，尝试其他选择器")
                slider_selectors = [
                    ".em_slider_knob",
                    "[class*='slider_knob']",
                    "[class*='slider']",
                    "[class*='slide']"
                ]
                
                for selector in slider_selectors:
                    try:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        for element in elements:
                            if element.is_displayed() and element.is_enabled():
                                slider = element
                                logging.info(f"找到滑块元素: {selector}")
                                break
                        if slider:
                            break
                    except:
                        continue
            
            if not slider:
                logging.warning("未找到滑块元素，无法执行滑动")
                return False
            
            # 执行滑动
            return self._perform_slide(slider, distance)
            
        except Exception as e:
            logging.error(f"执行滑动时出错: {str(e)}")
            return False
    
    def _perform_slide(self, slider, distance):
        """
        执行滑动操作
        """
        try:
            # 生成人类般的滑动轨迹
            tracks = self._generate_tracks(distance)
            
            # 移动到滑块位置
            ActionChains(self.driver).move_to_element(slider).perform()
            time.sleep(random.uniform(0.2, 0.4))
            
            # 按下并开始滑动
            action = ActionChains(self.driver)
            action.click_and_hold(slider)
            time.sleep(random.uniform(0.2, 0.3))  # 按下后稍等片刻
            
            # 执行滑动轨迹
            for track in tracks:
                action.move_by_offset(track, 0)
                time.sleep(random.uniform(0.01, 0.03))
            
            # 停顿后释放
            time.sleep(random.uniform(0.1, 0.3))
            action.release()
            action.perform()
            
            # 等待验证结果
            time.sleep(2)
            
            return self._check_success()
            
        except Exception as e:
            logging.error(f"执行滑动时出错: {str(e)}")
            return False
    
    def _generate_tracks(self, distance):
        """
        生成人类般的滑动轨迹
        """
        # 添加微小的距离调整，避免完全精确的距离
        distance = distance * random.uniform(0.96, 1.03)
        
        tracks = []
        current = 0
        mid = distance * 0.8  # 80%处开始减速
        t = 0.2
        v = 0
        
        while current < distance:
            if current < mid:
                a = random.uniform(2, 4)  # 加速
            else:
                a = random.uniform(-3, -1)  # 减速
            
            move = v * t + 0.5 * a * t * t
            v = v + a * t
            current += move
            
            if current > distance:
                move = distance - (current - move)
            
            if move > 0:
                tracks.append(round(move))
        
        # 添加一些回退和微调，模拟人类操作
        for _ in range(random.randint(2, 3)):
            tracks.append(-random.randint(1, 3))
        
        for _ in range(random.randint(1, 2)):
            tracks.append(random.randint(1, 2))
        
        return tracks
    
    def _check_success(self):
        """
        检查验证是否成功
        """
        try:
            # 等待一段时间让验证结果显示
            time.sleep(1)
            
            # 检查成功标志
            success_indicators = [
                "成功", "success", "验证通过", "verified"
            ]
            
            page_source = self.driver.page_source.lower()
            for indicator in success_indicators:
                if indicator.lower() in page_source:
                    return True
            
            # 检查是否还有验证码元素
            try:
                captcha_elements = self.driver.find_elements(By.CSS_SELECTOR, "[class*='captcha'], [class*='verify']")
                if not captcha_elements:
                    return True
            except:
                pass
            
            # 检查URL是否改变（可能跳转到了目标页面）
            current_url = self.driver.current_url
            if "captcha" not in current_url.lower() and "verify" not in current_url.lower():
                return True
            
            return False
            
        except Exception as e:
            logging.error(f"检查验证结果时出错: {str(e)}")
            return False
    
    def _solve_generic_captcha(self):
        """
        通用验证码解决方法
        """
        try:
            logging.info("尝试通用验证码解决方法")
            
            # 尝试点击页面中的可交互元素
            clickable_elements = self.driver.find_elements(By.CSS_SELECTOR, "button, input[type='button'], [onclick], [role='button']")
            
            for element in clickable_elements:
                try:
                    if element.is_displayed() and element.is_enabled():
                        element_text = element.text.lower()
                        if any(keyword in element_text for keyword in ["验证", "确认", "提交", "继续"]):
                            element.click()
                            time.sleep(2)
                            if self._check_success():
                                return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            logging.error(f"通用验证码解决方法出错: {str(e)}")
            return False
    
    def close(self):
        """关闭浏览器"""
        close_browser(self.driver)
        self.driver = None
        self.wait = None


def solve_captcha(url, max_retry=3, headless=True):
    """
    便捷函数：解决指定URL的验证码
    
    :param url: 验证码页面URL
    :param max_retry: 最大重试次数
    :param headless: 是否使用无头模式
    :return: 是否成功
    """
    solver = SimpleCaptchaSolver(max_retry=max_retry, headless=headless)
    try:
        for attempt in range(max_retry):
            logging.info(f"第{attempt+1}次尝试解决验证码...")
            if solver.solve_captcha(url):
                logging.info("验证码解决成功")
                return True
            time.sleep(random.uniform(1, 3))
        
        logging.warning("所有尝试均失败")
        return False
        
    except Exception as e:
        logging.error(f"验证码解决过程出错: {str(e)}")
        return False
    finally:
        solver.close()
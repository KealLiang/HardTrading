#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动作录制和回放脚本
支持录制和重复执行：点击、滚动、区域截图
"""

import time
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
import os

try:
    import pyautogui
    from pynput import mouse as pynput_mouse
except ImportError as e:
    print(f"缺少依赖库: {e}")
    print("请运行: pip install pyautogui pynput")
    exit(1)

class ActionRecorder:
    def __init__(self):
        self.actions = []
        self.is_recording = False
        self.is_playing = False
        self.recording_thread = None
        self.playing_thread = None
        self._record_last_ts = None
        
        # 播放参数（默认值）
        self.play_speed = 1.0  # 1.0=按原速，0.5=放慢，2.0=加速
        self.min_interval = 0.08  # 每步最小间隔秒
        self.scroll_settle_wait = 0.3  # 滚动后额外等待秒
        # 滚动回放控制（缩放、分块、残差）
        self.scroll_scale = 80.0  # 将录制的dy放大为滚动步数（垂直）
        self.hscroll_scale = 80.0  # 将录制的dx放大为滚动步数（水平）
        self.scroll_chunk = 30     # 单次发送的最大滚动步数，避免过大导致丢失
        self.scroll_min_step = 1   # 最小生效步数，避免被四舍五入为0
        self._scroll_residual = 0.0
        self._hscroll_residual = 0.0
        
        # 设置pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
        
        # 创建GUI
        self.setup_gui()
        
    def setup_gui(self):
        """创建图形界面"""
        self.root = tk.Tk()
        self.root.title("动作录制器")
        self.root.geometry("720x560")
        
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 控制按钮
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=0, column=0, columnspan=2, pady=10, sticky=(tk.W, tk.E))
        
        self.record_btn = ttk.Button(control_frame, text="开始录制", command=self.start_recording)
        self.record_btn.grid(row=0, column=0, padx=5)
        
        self.stop_btn = ttk.Button(control_frame, text="停止录制", command=self.stop_recording, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=5)
        
        self.play_btn = ttk.Button(control_frame, text="开始回放", command=self.start_playing)
        self.play_btn.grid(row=0, column=2, padx=5)
        
        self.stop_play_btn = ttk.Button(control_frame, text="停止回放", command=self.stop_playing, state="disabled")
        self.stop_play_btn.grid(row=0, column=3, padx=5)
        
        # 播放参数
        params_frame = ttk.LabelFrame(main_frame, text="回放参数", padding="8")
        params_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E))
        
        ttk.Label(params_frame, text="回放速度（倍速）").grid(row=0, column=0, sticky=tk.W)
        self.speed_var = tk.DoubleVar(value=self.play_speed)
        ttk.Entry(params_frame, textvariable=self.speed_var, width=8).grid(row=0, column=1, padx=6)
        
        ttk.Label(params_frame, text="最小间隔（秒）").grid(row=0, column=2, sticky=tk.W)
        self.min_interval_var = tk.DoubleVar(value=self.min_interval)
        ttk.Entry(params_frame, textvariable=self.min_interval_var, width=8).grid(row=0, column=3, padx=6)
        
        ttk.Label(params_frame, text="滚动后等待（秒）").grid(row=0, column=4, sticky=tk.W)
        self.scroll_wait_var = tk.DoubleVar(value=self.scroll_settle_wait)
        ttk.Entry(params_frame, textvariable=self.scroll_wait_var, width=8).grid(row=0, column=5, padx=6)
        
        ttk.Button(params_frame, text="应用参数", command=self.apply_params).grid(row=0, column=6, padx=8)
        
        # 新增：滚动缩放与分块设置
        ttk.Label(params_frame, text="垂直滚动缩放").grid(row=1, column=0, sticky=tk.W)
        self.scroll_scale_var = tk.DoubleVar(value=self.scroll_scale)
        ttk.Entry(params_frame, textvariable=self.scroll_scale_var, width=8).grid(row=1, column=1, padx=6)
        
        ttk.Label(params_frame, text="水平滚动缩放").grid(row=1, column=2, sticky=tk.W)
        self.hscroll_scale_var = tk.DoubleVar(value=self.hscroll_scale)
        ttk.Entry(params_frame, textvariable=self.hscroll_scale_var, width=8).grid(row=1, column=3, padx=6)
        
        ttk.Label(params_frame, text="滚动分块步数").grid(row=1, column=4, sticky=tk.W)
        self.scroll_chunk_var = tk.IntVar(value=self.scroll_chunk)
        ttk.Entry(params_frame, textvariable=self.scroll_chunk_var, width=8).grid(row=1, column=5, padx=6)
        
        # 状态显示
        status_frame = ttk.LabelFrame(main_frame, text="状态", padding="5")
        status_frame.grid(row=2, column=0, columnspan=2, pady=10, sticky=(tk.W, tk.E))
        
        self.status_label = ttk.Label(status_frame, text="就绪")
        self.status_label.grid(row=0, column=0)
        
        # 动作列表
        list_frame = ttk.LabelFrame(main_frame, text="录制的动作", padding="5")
        list_frame.grid(row=3, column=0, columnspan=2, pady=10, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        columns = ("时间", "类型", "详情")
        self.action_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=12)
        for col in columns:
            self.action_tree.heading(col, text=col)
            self.action_tree.column(col, width=180)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.action_tree.yview)
        self.action_tree.configure(yscrollcommand=scrollbar.set)
        self.action_tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # 文件操作
        file_frame = ttk.Frame(main_frame)
        file_frame.grid(row=4, column=0, columnspan=2, pady=10, sticky=(tk.W, tk.E))
        
        ttk.Button(file_frame, text="保存动作", command=self.save_actions).grid(row=0, column=0, padx=5)
        ttk.Button(file_frame, text="加载动作", command=self.load_actions).grid(row=0, column=1, padx=5)
        ttk.Button(file_frame, text="清空动作", command=self.clear_actions).grid(row=0, column=2, padx=5)
        
        # 截图区域选择
        screenshot_frame = ttk.LabelFrame(main_frame, text="区域截图", padding="5")
        screenshot_frame.grid(row=5, column=0, columnspan=2, pady=10, sticky=(tk.W, tk.E))
        
        ttk.Button(screenshot_frame, text="选择截图区域", command=self.select_screenshot_area).grid(row=0, column=0, padx=5)
        ttk.Button(screenshot_frame, text="执行截图", command=self.take_screenshot).grid(row=0, column=1, padx=5)
        
        self.screenshot_area = None
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
    def apply_params(self):
        try:
            speed = float(self.speed_var.get())
            min_iv = float(self.min_interval_var.get())
            scroll_wait = float(self.scroll_wait_var.get())
            v_scale = float(self.scroll_scale_var.get())
            h_scale = float(self.hscroll_scale_var.get())
            chunk = int(self.scroll_chunk_var.get())
            if speed <= 0:
                raise ValueError("回放速度必须>0")
            if min_iv < 0:
                raise ValueError("最小间隔必须>=0")
            if scroll_wait < 0:
                raise ValueError("滚动后等待必须>=0")
            if v_scale <= 0 or h_scale <= 0:
                raise ValueError("滚动缩放必须>0")
            if chunk <= 0:
                raise ValueError("滚动分块步数必须>0")
            self.play_speed = speed
            self.min_interval = min_iv
            self.scroll_settle_wait = scroll_wait
            self.scroll_scale = v_scale
            self.hscroll_scale = h_scale
            self.scroll_chunk = chunk
            # 重新应用时重置残差，避免历史误差影响
            self._scroll_residual = 0.0
            self._hscroll_residual = 0.0
            self.status_label.config(text=f"已应用参数: 速度x{self.play_speed}, 最小间隔{self.min_interval}s, 滚动等待{self.scroll_settle_wait}s, 垂直缩放{self.scroll_scale}, 水平缩放{self.hscroll_scale}, 分块{self.scroll_chunk}")
        except Exception as e:
            messagebox.showerror("错误", f"参数无效: {e}")
        
    def start_recording(self):
        if self.is_playing:
            messagebox.showwarning("警告", "请先停止回放")
            return
        self.actions = []
        self.is_recording = True
        self._record_last_ts = time.time()
        self.record_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_label.config(text="正在录制... 点击界面外或其他窗口进行操作")
        self.recording_thread = threading.Thread(target=self._record_actions, name="record-thread", daemon=True)
        self.recording_thread.start()
        
    def stop_recording(self):
        self.is_recording = False
        self.record_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_label.config(text=f"录制完成，共{len(self.actions)}个动作")
        self.update_action_list()
        
    def _normalize_button(self, button_obj):
        try:
            if button_obj == pynput_mouse.Button.left:
                return "left"
            if button_obj == pynput_mouse.Button.right:
                return "right"
            if button_obj == pynput_mouse.Button.middle:
                return "middle"
        except Exception:
            pass
        return "left"
        
    def _append_action(self, action: dict):
        now_ts = time.time()
        dt = now_ts - (self._record_last_ts or now_ts)
        self._record_last_ts = now_ts
        action["dt"] = dt
        self.actions.append(action)
        self.root.after(0, self.update_action_list)
        
    def _record_actions(self):
        def on_click(x, y, button, pressed):
            if pressed and self.is_recording:
                self._append_action({
                    "type": "click",
                    "x": x,
                    "y": y,
                    "button": self._normalize_button(button),
                    "timestamp": time.time()
                })
        
        def on_scroll(x, y, dx, dy):
            if self.is_recording:
                self._append_action({
                    "type": "scroll",
                    "x": x,
                    "y": y,
                    "dx": dx,
                    "dy": dy,
                    "timestamp": time.time()
                })
        
        try:
            with pynput_mouse.Listener(on_click=on_click, on_scroll=on_scroll) as listener:
                while self.is_recording:
                    time.sleep(0.02)
                listener.stop()
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("错误", f"录制监听失败: {e}"))
    
    def start_playing(self):
        if self.is_recording:
            messagebox.showwarning("警告", "请先停止录制")
            return
        if not self.actions:
            messagebox.showwarning("警告", "没有可回放的动作")
            return
        self.is_playing = True
        self.play_btn.config(state="disabled")
        self.stop_play_btn.config(state="normal")
        self.status_label.config(text="正在回放...")
        self.playing_thread = threading.Thread(target=self._play_actions, name="play-thread", daemon=True)
        self.playing_thread.start()
        
    def stop_playing(self):
        self.is_playing = False
        self.play_btn.config(state="normal")
        self.stop_play_btn.config(state="normal")
        self.status_label.config(text="回放已停止")
        
    def _sleep_responsive(self, seconds):
        end = time.time() + max(0, seconds)
        while self.is_playing and time.time() < end:
            time.sleep(0.01)
        
    def _apply_scroll(self, dx, dy, x, y):
        """根据缩放、残差与分块发送滚动，尽量复现原手势力度。"""
        # 对齐位置
        try:
            pyautogui.moveTo(x, y)
        except Exception:
            pass
        
        # 垂直滚动
        total_v = dy * self.scroll_scale + self._scroll_residual
        clicks_v = 0
        if abs(total_v) >= self.scroll_min_step:
            clicks_v = int(total_v)
            self._scroll_residual = total_v - clicks_v
        else:
            self._scroll_residual = total_v
        
        # 水平滚动
        total_h = dx * self.hscroll_scale + self._hscroll_residual
        clicks_h = 0
        if abs(total_h) >= self.scroll_min_step:
            clicks_h = int(total_h)
            self._hscroll_residual = total_h - clicks_h
        else:
            self._hscroll_residual = total_h
        
        # 分块发送，避免一次性过大
        try:
            if clicks_v != 0:
                remaining = clicks_v
                step_sign = 1 if remaining > 0 else -1
                while remaining != 0 and self.is_playing:
                    step = step_sign * min(self.scroll_chunk, abs(remaining))
                    pyautogui.scroll(step)
                    remaining -= step
                    time.sleep(0.005)
            
            if clicks_h != 0:
                if hasattr(pyautogui, "hscroll"):
                    remaining = clicks_h
                    step_sign = 1 if remaining > 0 else -1
                    while remaining != 0 and self.is_playing:
                        step = step_sign * min(self.scroll_chunk, abs(remaining))
                        pyautogui.hscroll(step)
                        remaining -= step
                        time.sleep(0.005)
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("错误", f"滚动执行失败: {str(e)}"))
        
    def _play_actions(self):
        try:
            for i, action in enumerate(self.actions):
                if not self.is_playing:
                    break
                
                # 按录制节奏等待
                dt = action.get("dt", 0.0)
                wait_time = max(self.min_interval, dt / max(1e-6, self.play_speed))
                self._sleep_responsive(wait_time)
                
                self.root.after(0, lambda i=i: self.status_label.config(text=f"回放中... ({i+1}/{len(self.actions)})"))
                
                if action["type"] == "click":
                    pyautogui.click(action["x"], action["y"], button=action["button"]) 
                elif action["type"] == "scroll":
                    self._apply_scroll(action.get("dx", 0), action.get("dy", 0), action["x"], action["y"]) 
                    # 滚动后额外等待，避免界面未稳定
                    self._sleep_responsive(self.scroll_settle_wait)
                
            if self.is_playing:
                self.root.after(0, lambda: self.status_label.config(text="回放完成"))
                self.root.after(0, lambda: self.play_btn.config(state="normal"))
                self.root.after(0, lambda: self.stop_play_btn.config(state="disabled"))
                self.is_playing = False
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("错误", f"回放出错: {str(e)}"))
            self.root.after(0, lambda: self.play_btn.config(state="normal"))
            self.root.after(0, lambda: self.stop_play_btn.config(state="disabled"))
            self.is_playing = False
    
    def update_action_list(self):
        for item in self.action_tree.get_children():
            self.action_tree.delete(item)
        for action in self.actions:
            timestamp = datetime.fromtimestamp(action["timestamp"]).strftime("%H:%M:%S.%f")[:-3]
            if action["type"] == "click":
                details = f"({action['x']}, {action['y']}) {action['button']} dt={action.get('dt', 0):.3f}s"
            elif action["type"] == "scroll":
                details = f"({action['x']}, {action['y']}) dx={action.get('dx', 0)}, dy={action.get('dy', 0)} dt={action.get('dt', 0):.3f}s"
            else:
                details = str(action)
            self.action_tree.insert("", "end", values=(timestamp, action["type"], details))
    
    def select_screenshot_area(self):
        self.status_label.config(text="请拖拽选择截图区域，按ESC取消")
        self.screenshot_window = tk.Toplevel(self.root)
        self.screenshot_window.attributes('-fullscreen', True)
        self.screenshot_window.attributes('-alpha', 0.3)
        self.screenshot_window.configure(bg='black')
        self.screenshot_window.attributes('-topmost', True)
        self.screenshot_canvas = tk.Canvas(self.screenshot_window, highlightthickness=0)
        self.screenshot_canvas.pack(fill=tk.BOTH, expand=True)
        self.screenshot_canvas.bind('<Button-1>', self.start_selection)
        self.screenshot_canvas.bind('<B1-Motion>', self.update_selection)
        self.screenshot_canvas.bind('<ButtonRelease-1>', self.end_selection)
        self.screenshot_window.bind('<Escape>', self.cancel_selection)
        self.selection_start = None
        self.selection_rect = None
        
    def start_selection(self, event):
        self.selection_start = (event.x, event.y)
        
    def update_selection(self, event):
        if self.selection_start:
            if self.selection_rect:
                self.screenshot_canvas.delete(self.selection_rect)
            self.selection_rect = self.screenshot_canvas.create_rectangle(
                self.selection_start[0], self.selection_start[1],
                event.x, event.y,
                outline='red', width=2
            )
    
    def end_selection(self, event):
        if self.selection_start:
            x1, y1 = self.selection_start
            x2, y2 = event.x, event.y
            left = min(x1, x2)
            top = min(y1, y2)
            right = max(x1, x2)
            bottom = max(y1, y2)
            self.screenshot_area = (left, top, right - left, bottom - top)
            self.screenshot_window.destroy()
            self.status_label.config(text=f"已选择截图区域: {self.screenshot_area}")
    
    def cancel_selection(self, event):
        self.screenshot_window.destroy()
        self.status_label.config(text="已取消选择")
    
    def take_screenshot(self):
        if not self.screenshot_area:
            messagebox.showwarning("警告", "请先选择截图区域")
            return
        try:
            screenshot = pyautogui.screenshot(region=self.screenshot_area)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{timestamp}.png"
            screenshot.save(filename)
            messagebox.showinfo("成功", f"截图已保存: {filename}")
            self.status_label.config(text=f"截图已保存: {filename}")
        except Exception as e:
            messagebox.showerror("错误", f"截图失败: {str(e)}")
    
    def save_actions(self):
        if not self.actions:
            messagebox.showwarning("警告", "没有动作可保存")
            return
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(self.actions, f, indent=2, ensure_ascii=False)
                messagebox.showinfo("成功", f"动作已保存到: {filename}")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败: {str(e)}")
    
    def load_actions(self):
        filename = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    self.actions = json.load(f)
                self.update_action_list()
                messagebox.showinfo("成功", f"已加载 {len(self.actions)} 个动作")
            except Exception as e:
                messagebox.showerror("错误", f"加载失败: {str(e)}")
    
    def clear_actions(self):
        if messagebox.askyesno("确认", "确定要清空所有动作吗？"):
            self.actions = []
            self.update_action_list()
            self.status_label.config(text="动作列表已清空")
    
    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    try:
        app = ActionRecorder()
        app.run()
    except KeyboardInterrupt:
        print("\n程序已退出")
    except Exception as e:
        print(f"程序出错: {e}")
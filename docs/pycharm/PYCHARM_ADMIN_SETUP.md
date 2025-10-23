## PyCharm 以管理员权限运行脚本配置指南

### 问题说明
通达信自动截图脚本需要激活窗口权限，PyCharm 直接运行时可能报错：
```
ERROR - 激活通达信窗口失败: Error code from Windows: 5 - 拒绝访问。
```

### 解决方案

#### 方案1：让 PyCharm 始终以管理员身份运行（推荐）

1. 找到 PyCharm 的快捷方式或可执行文件
   - 桌面快捷方式：右键 → 属性
   - 开始菜单：右键 PyCharm → 更多 → 打开文件位置 → 右键快捷方式 → 属性

2. 在"快捷方式"选项卡中，点击"高级"按钮

3. 勾选"用管理员身份运行"

4. 点击"确定"保存

5. 重启 PyCharm

**优点**：一次配置，永久生效  
**缺点**：所有项目都以管理员权限运行

---

#### 方案2：配置单个运行配置以管理员运行

PyCharm 本身不支持单个运行配置以管理员运行，但可以通过以下方式：

**方法A：使用外部工具**

1. 打开 PyCharm：`File` → `Settings` → `Tools` → `External Tools`

2. 点击 `+` 添加新工具：
   - Name: `Run as Admin`
   - Program: `powershell.exe`
   - Arguments: `-Command "Start-Process -Verb RunAs -FilePath 'conda' -ArgumentList 'run', '-n', 'trading', 'python', '$FilePath$'"`
   - Working directory: `$ProjectFileDir$`

3. 使用时：右键脚本文件 → `External Tools` → `Run as Admin`

**方法B：创建批处理脚本（最简单）**

在项目根目录创建 `run_admin.bat`：
```batch
@echo off
cd /d "%~dp0"
powershell -Command "Start-Process cmd -Verb RunAs -ArgumentList '/k', 'conda activate trading && python automation/tdx_auction_screenshot.py start'"
```

使用时：双击 `run_admin.bat` 即可

---

#### 方案3：临时以管理员运行（每次手动）

1. 以管理员身份打开 PowerShell 或 CMD

2. 激活环境并运行：
```bash
cd D:\Trading
conda activate trading
python automation/tdx_auction_screenshot.py start
```

---

### 验证是否生效

运行脚本后，日志中不应出现"拒绝访问"错误：
```
✅ 正常：INFO - 开始 0915 截图流程...
❌ 异常：ERROR - 激活通达信窗口失败: Error code from Windows: 5
```

### 注意事项

- 以管理员权限运行后，脚本可以正常激活通达信窗口
- 如果仍有问题，检查通达信是否也以管理员权限运行（两者权限需一致）
- 定时任务建议使用 Windows 任务计划程序配置开机自启 
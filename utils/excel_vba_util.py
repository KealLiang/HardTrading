import os

import pythoncom
import win32com.client


def add_vba_to_sheet(excel_file, vba_file, sheet_name=None, save_as=None):
    """
    将VBA脚本添加到Excel文件的指定工作表中
    
    参数:
        excel_file (str): Excel文件的路径
        vba_file (str): 包含VBA代码的文件路径
        sheet_name (str, optional): 要添加代码的工作表名称。如果为None，使用第一个工作表
        save_as (str, optional): 保存结果的文件路径。如果为None，使用原文件路径但扩展名改为.xlsm
        
    返回:
        str: 保存的xlsm文件路径
    """
    # 确保文件路径是绝对路径
    excel_file = os.path.abspath(excel_file)
    vba_file = os.path.abspath(vba_file)

    # 如果没有指定保存路径，创建默认路径
    if save_as is None:
        save_as = os.path.splitext(excel_file)[0] + '.xlsm'

    # 读取VBA代码
    with open(vba_file, 'r', encoding='utf-8') as f:
        vba_code = f.read()

    # 初始化COM接口
    pythoncom.CoInitialize()

    try:
        # 创建Excel应用实例
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False

        # 尝试打开工作簿
        try:
            wb = excel.Workbooks.Open(excel_file)
        except Exception as e:
            print(f"打开Excel文件失败: {e}")
            excel.Quit()
            return None

        # 找到目标工作表
        if sheet_name is None:
            # 使用第一个工作表
            ws = wb.Worksheets(1)
            sheet_name = ws.Name
        else:
            # 尝试找到指定名称的工作表
            try:
                ws = wb.Worksheets(sheet_name)
            except:
                print(f"找不到工作表 '{sheet_name}'，使用第一个工作表")
                ws = wb.Worksheets(1)
                sheet_name = ws.Name

        # 确保VBA项目是可访问的
        try:
            vba_project = wb.VBProject
        except Exception as e:
            print(f"无法访问VBA项目: {e}")
            print("请确保Excel信任中心设置允许访问VBA项目对象模型")
            wb.Close(False)
            excel.Quit()
            return None

        # 关键修改：直接获取工作表的代码模块
        # 工作表模块的名称是"Sheet1"等原始工作表名称，而不是用户定义的工作表名称
        sheet_code_name = ws.CodeName  # 获取工作表的代码名称（例如"Sheet1"）

        # 找到工作表的代码模块
        sheet_module = None
        for component in vba_project.VBComponents:
            if component.Name == sheet_code_name:
                sheet_module = component
                break

        if sheet_module is None:
            print(f"警告: 无法找到工作表代码模块，将尝试使用其它方法")
            # 尝试使用类型查找工作表模块
            for component in vba_project.VBComponents:
                if component.Type == 100:  # 100 = vbext_ct_Document
                    sheet_module = component
                    print(f"使用类型匹配找到工作表模块: {component.Name}")
                    break

        if sheet_module is None:
            print(f"错误: 无法找到工作表代码模块")
            wb.Close(False)
            excel.Quit()
            return None

        # 清空现有代码并添加新代码
        if sheet_module.CodeModule.CountOfLines > 0:
            sheet_module.CodeModule.DeleteLines(1, sheet_module.CodeModule.CountOfLines)
        sheet_module.CodeModule.AddFromString(vba_code)

        # 保存为启用宏的工作簿
        wb.SaveAs(save_as, 52)  # 52 = xlOpenXMLWorkbookMacroEnabled
        print(f"已成功添加VBA脚本到工作表「{sheet_name}」(代码名:{sheet_code_name})，并保存为: {save_as}")

        # 关闭工作簿
        wb.Close(False)

        return save_as

    except Exception as e:
        print(f"添加VBA脚本失败: {e}")
        import traceback
        traceback.print_exc()
        return None

    finally:
        # 退出Excel
        try:
            excel.Quit()
        except:
            pass

        # 释放COM资源
        pythoncom.CoUninitialize()


# 使用示例
if __name__ == "__main__":
    # 示例用法
    excel_file = "path/to/your.xlsx"
    vba_file = "path/to/your.vba"
    add_vba_to_sheet(excel_file, vba_file, "Sheet1")

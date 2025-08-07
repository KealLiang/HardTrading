import logging
import sys


class PrintToLoggingHandler:
    """
    将print输出重定向到logging的自定义处理器
    
    这个类可以捕获所有print()输出并将其重定向到logging系统，
    使得print输出也能被记录到日志文件中。
    
    用法示例:
    ```
    # 保存原始stdout
    original_stdout = sys.stdout
    
    # 创建处理器并重定向
    handler = PrintToLoggingHandler(logging.getLogger('print'))
    sys.stdout = handler
    
    # 执行会产生print输出的代码
    some_function_with_print()
    
    # 恢复原始stdout
    sys.stdout = original_stdout
    handler.flush()  # 确保所有缓存内容都被写入
    ```
    """
    def __init__(self, logger, level=logging.INFO):
        """
        初始化处理器
        
        Args:
            logger: logging.Logger对象，用于记录消息
            level: 日志级别，默认为INFO
        """
        self.logger = logger
        self.level = level
        self.buffer = ""
    
    def write(self, message):
        """
        处理写入的消息
        
        Args:
            message: 要写入的消息
        """
        # 缓存消息直到遇到换行符
        self.buffer += message
        if '\n' in self.buffer:
            lines = self.buffer.split('\n')
            # 处理除最后一个元素外的所有行（最后一个可能是不完整的）
            for line in lines[:-1]:
                if line.strip():  # 只记录非空行
                    self.logger.log(self.level, line.strip())
            # 保留最后的不完整行
            self.buffer = lines[-1]
    
    def flush(self):
        """刷新缓存中的内容"""
        if self.buffer.strip():
            self.logger.log(self.level, self.buffer.strip())
            self.buffer = ""


def redirect_print_to_logger(logger=None, level=logging.INFO):
    """
    创建一个上下文管理器，在指定范围内将print输出重定向到logger
    
    Args:
        logger: 要使用的logger，如果为None则使用root logger
        level: 日志级别，默认为INFO
        
    Returns:
        上下文管理器对象
        
    用法示例:
    ```
    with redirect_print_to_logger():
        print("这条消息会被记录到日志中")
    ```
    """
    class PrintRedirector:
        def __init__(self, logger, level):
            self.logger = logger or logging.getLogger()
            self.level = level
            self.original_stdout = None
            self.handler = None
            
        def __enter__(self):
            self.original_stdout = sys.stdout
            self.handler = PrintToLoggingHandler(self.logger, self.level)
            sys.stdout = self.handler
            return self
            
        def __exit__(self, exc_type, exc_val, exc_tb):
            sys.stdout = self.original_stdout
            if self.handler:
                self.handler.flush()
    
    return PrintRedirector(logger, level) 
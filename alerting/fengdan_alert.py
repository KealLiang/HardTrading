import time
import threading
import winsound
import akshare as ak
from pytdx.hq import TdxHq_API

tdx_host = '202.96.138.90'

def test_pytdx_connection(stock_code='000001', retries=3):
    """
    pytdx 提供了命令行工具，可以验证host连通性
    命令 > hqget --all
    :param stock_code:
    :param retries:
    :return:
    """
    api = TdxHq_API()
    market_code = 0 if stock_code.startswith(('0', '3')) else 1

    for attempt in range(retries):
        try:
            if not api.connect(tdx_host, 7709):
                print(f"连接服务器失败，重试中... ({attempt + 1}/{retries})")
                time.sleep(2)
                continue

            quotes = api.get_security_quotes([(market_code, stock_code)])
            if not quotes:
                print(f"未获取到股票 {stock_code} 的数据，重试中... ({attempt + 1}/{retries})")
                time.sleep(2)
                continue

            market_data = quotes[0]
            print(f"连接成功！股票 {stock_code} 的基本信息如下：")
            print(f"当前价格: {market_data['price']}")
            print(f"买一价: {market_data['bid1']}")
            print(f"卖一价: {market_data['ask1']}")
            print(f"买一量: {market_data['bid_vol1']}")
            print(f"卖一量: {market_data['ask_vol1']}")
            return True

        except Exception as e:
            print(f"连接或获取数据失败: {e}，重试中... ({attempt + 1}/{retries})")
            time.sleep(2)

        finally:
            api.disconnect()

    print(f"重试 {retries} 次后仍未成功连接或获取数据")
    return False

class LimitMonitor:
    def __init__(self, stock_code, decrease_ratio=0.05, trade_date=None):
        self.stock_code = stock_code
        self.decrease_ratio = decrease_ratio
        self.trade_date = trade_date if trade_date else time.strftime("%Y%m%d")
        self.api = TdxHq_API()
        self.stop_event = threading.Event()
        self.stock_name = self.get_stock_name()

        self.previous_close_price = self.get_previous_close_price()
        self.upper_limit_price, self.lower_limit_price = self.calculate_limit_prices()

    def get_stock_name(self):
        stock_info = ak.stock_individual_info_em(symbol=self.stock_code)
        return stock_info[stock_info['item'] == '股票简称']['value'].values[0]
    
    def get_previous_close_price(self):
        try:
            self.connect_to_api()
            market_code = self.get_market_code()
            quotes = self.api.get_security_quotes([(market_code, self.stock_code)])
            if not quotes:
                raise ValueError(f"未获取到股票 {self.stock_code} 的实时行情数据")
            return quotes[0]['last_close']
        except Exception as e:
            print(f"获取前一日收盘价失败: {e}")
            return None
        finally:
            self.api.disconnect()

    def get_market_code(self):
        if self.stock_code.startswith(('0', '3')):
            return 0
        elif self.stock_code.startswith(('6', '9')):
            return 1
        else:
            raise ValueError(f"未知的股票代码: {self.stock_code}")

    def calculate_limit_prices(self):
        if self.stock_code.startswith(('0', '3', '6')):
            limit_ratio = 0.1
        elif self.stock_code.startswith('688'):
            limit_ratio = 0.2
        elif self.stock_code.startswith('300'):
            limit_ratio = 0.2
        else:
            raise ValueError(f"未知的股票代码: {self.stock_code}")

        upper_limit_price = round(self.previous_close_price * (1 + limit_ratio), 2)
        lower_limit_price = round(self.previous_close_price * (1 - limit_ratio), 2)
        return upper_limit_price, lower_limit_price

    def connect_to_api(self):
        self.api.connect(tdx_host, 7709)
        return self.api

    def get_real_time_data(self):
        try:
            self.connect_to_api()
            market_code = self.get_market_code()
            quotes = self.api.get_security_quotes([(market_code, self.stock_code)])
            if not quotes:
                print(f"未获取到股票 {self.stock_code} 的实时行情数据")
                return None

            market_data = quotes[0]
            bid1 = market_data['bid1']
            bid_vol1 = market_data['bid_vol1']
            ask1 = market_data['ask1']
            ask_vol1 = market_data['ask_vol1']

            bid1_amount = bid1 * bid_vol1
            ask1_amount = ask1 * ask_vol1

            return bid1, bid1_amount, ask1, ask1_amount
        except Exception as e:
            print(f"实时数据获取失败: {e}")
            return None
        finally:
            self.api.disconnect()

    def monitor_limit(self):
        prev_buy1_amount = None
        prev_sell1_amount = None
        counter = 0

        try:
            while not self.stop_event.is_set():
                real_time_data = self.get_real_time_data()

                if real_time_data:
                    buy1_price, buy1_amount, sell1_price, sell1_amount = real_time_data
                    counter += 1
                    if counter >= 5:
                        print(f"[{self.stock_name} {self.stock_code}] 买一价: {buy1_price:<8}, 买一额: {float(buy1_amount)/100:<8.2f}万元;\t卖一价: {sell1_price:<8}, 卖一额: {float(sell1_amount)/100:<8.2f}万元")
                        counter = 0

                    if prev_buy1_amount and (prev_buy1_amount - buy1_amount) / prev_buy1_amount >= self.decrease_ratio:
                        print(f"警告！买一封单额减少超过{self.decrease_ratio * 100}%！")
                        winsound.Beep(1000, 500)  # 发出声音，频率1000Hz，持续500毫秒

                    if prev_sell1_amount and (prev_sell1_amount - sell1_amount) / prev_sell1_amount >= self.decrease_ratio:
                        print(f"警告！卖一封单额减少超过{self.decrease_ratio * 100}%！")
                        winsound.Beep(1000, 500)

                    prev_buy1_amount = buy1_amount
                    prev_sell1_amount = sell1_amount

                time.sleep(3)
        except KeyboardInterrupt:
            self.stop_event.set()
        finally:
            self.api.disconnect()

    def start_monitoring(self):
        print(f"开始监控股票: {self.stock_code}")
        self.monitor_limit()

    def stop_monitoring(self):
        print(f"停止监控股票: {self.stock_code}")
        self.stop_event.set()

def monitor_multiple_stocks(stock_codes, decrease_ratio=0.05):
    monitors = []
    threads = []

    for code in stock_codes:
        monitor = LimitMonitor(code, decrease_ratio)
        monitors.append(monitor)
        thread = threading.Thread(target=monitor.start_monitoring)
        threads.append(thread)

    for thread in threads:
        thread.start()

    try:
        while True:
            time.sleep(3)
    except KeyboardInterrupt:
        print("Stopping all threads...")
        for monitor in monitors:
            monitor.stop_monitoring()
        for thread in threads:
            thread.join()

def test_pytdx():
    stock_code = '002265'
    if test_pytdx_connection(stock_code):
        print("pytdx 连接正常！")
    else:
        print("pytdx 连接失败，请检查网络或服务器状态。")

if __name__ == '__main__':
    # 检查 pytdx 连接
    # test_pytdx()
    
    # 监控板上单
    stock_codes = ['000001', '002291', '002265']
    monitor_multiple_stocks(stock_codes)
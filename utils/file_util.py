def save_list_to_file(data_list, filename='./data/result.txt'):
    """
    将list的内容保存到一个文本文件中。

    :param data_list: 包含LongTou对象的列表。
    :param filename: 要保存的文件名。
    """
    with open(filename, 'w', encoding='utf-8') as file:
        for stock in data_list:
            file.write(str(stock) + '\n')

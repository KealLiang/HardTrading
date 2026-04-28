import csv
import io
import logging
import os
from datetime import datetime

import pandas as pd
from tqdm import tqdm


STOCK_DATA_COLUMNS = [
    '日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率'
]

NUMERIC_COLUMNS = ['开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率']
PRICE_COLUMNS = ['开盘', '收盘', '最高', '最低']
ZERO_LIKE_COLUMNS = ['成交量', '成交额']


def clean_duplicate_stock_datas(data_dir='./data/astocks', clean_today_only=True, delete=False, target_date=None,
                                report_path='./data/astocks_duplicate_clean_report.txt'):
    """
    扫描并清理A股日线CSV中接口返回的跨日重复行情。

    重复定义：
        同一文件内，某一交易日除日期外的数据与前一条记录完全一致。

    保护规则：
        疑似停牌/空行情数据不自动删除，只记录为“需人工核对”。
        例如：开高低收等字段为空，成交字段为空或0。

    Args:
        data_dir: A股日线数据目录。
        clean_today_only: True只处理target_date当天；False处理历史所有日期。
        delete: False仅扫描报告；True删除可确认的重复行。
        target_date: 目标日期，支持YYYY-MM-DD或YYYYMMDD；默认今天。
        report_path: 扫描报告输出路径，每次运行覆盖写入。

    Returns:
        dict: 包含 duplicate_records 和 review_records。
    """
    target_date = _normalize_target_date(target_date)
    if not os.path.exists(data_dir):
        print(f"数据目录不存在: {data_dir}")
        return {'duplicate_records': [], 'review_records': []}

    csv_files = sorted(file for file in os.listdir(data_dir) if file.endswith('.csv'))
    duplicate_records = []
    review_records = []
    cleaned_files = 0

    mode_desc = f"仅{target_date}" if clean_today_only else "所有日期"
    action_desc = "删除" if delete else "扫描"
    print(f"开始{action_desc}A股重复行情数据，范围: {mode_desc}，目录: {data_dir}")

    for file_name in tqdm(csv_files, desc=f"{action_desc}重复行情", unit="file", ncols=100):
        file_path = os.path.join(data_dir, file_name)
        try:
            if clean_today_only:
                deletable_records, manual_review_records = _scan_latest_duplicate(file_path, file_name, target_date)
                duplicate_records.extend(deletable_records)
                review_records.extend(manual_review_records)

                if delete and deletable_records:
                    if _delete_latest_row_from_csv(file_path, target_date):
                        cleaned_files += 1
                continue

            df = _read_stock_csv(file_path)
            if df.empty or len(df) < 2:
                continue

            duplicate_mask = _find_duplicate_rows(df, clean_today_only, target_date)
            if not duplicate_mask.any():
                continue

            df['人工核对原因'] = df.apply(lambda row: '，'.join(_manual_review_reasons(row)), axis=1)
            review_mask = duplicate_mask & df['人工核对原因'].ne('')
            deletable_mask = duplicate_mask & ~review_mask

            duplicate_records.extend(_build_records(df[deletable_mask], df, file_name, '可删除重复'))
            review_records.extend(_build_records(df[review_mask], df, file_name, '需人工核对'))

            if delete and deletable_mask.any():
                cleaned_df = df[~deletable_mask].drop(columns=['日期文本'])
                cleaned_df['日期'] = cleaned_df['日期'].dt.strftime('%Y-%m-%d')
                cleaned_df.to_csv(file_path, index=False, header=False)
                cleaned_files += 1

        except Exception as e:
            logging.error(f"处理 {file_name} 时出错: {e}")

    _write_report(
        report_path=report_path,
        action_desc=action_desc,
        mode_desc=mode_desc,
        data_dir=data_dir,
        total_files=len(csv_files),
        duplicate_records=duplicate_records,
        review_records=review_records,
        cleaned_files=cleaned_files,
        delete=delete,
        include_raw_rows=clean_today_only,
    )

    print(f"\n{action_desc}完成：扫描 {len(csv_files)} 个CSV")
    print(f"可删除重复: {len(_group_records_by_file(duplicate_records))} 个文件，{len(duplicate_records)} 条记录")
    print(f"需人工核对: {len(_group_records_by_file(review_records))} 个文件，{len(review_records)} 条记录")
    print(f"报告已输出: {report_path}")
    if delete:
        print(f"已清理 {cleaned_files} 个文件，需人工核对记录未删除")
    elif duplicate_records:
        print("当前为扫描模式，未执行删除；确认后可设置 delete=True 清理可删除重复记录")

    return {
        'duplicate_records': duplicate_records,
        'review_records': review_records,
        'report_path': report_path,
    }


def _normalize_target_date(target_date):
    if target_date is None:
        return datetime.now().strftime('%Y-%m-%d')
    return pd.to_datetime(target_date).strftime('%Y-%m-%d')


def _read_stock_csv(file_path):
    df = pd.read_csv(file_path, header=None, names=STOCK_DATA_COLUMNS, dtype={'股票代码': str})
    if df.empty:
        return df

    df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
    df = df.dropna(subset=['日期']).sort_values('日期').reset_index(drop=True)
    df['日期文本'] = df['日期'].dt.strftime('%Y-%m-%d')

    for column in NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors='coerce')

    return df


def _scan_latest_duplicate(file_path, file_name, target_date):
    rows = _read_last_csv_rows(file_path, row_count=2)
    if len(rows) < 2:
        return [], []

    previous_row, current_row = rows[-2], rows[-1]
    previous_row = _normalize_csv_row(previous_row)
    current_row = _normalize_csv_row(current_row)
    current_date = _normalize_row_date(current_row[0])
    previous_date = _normalize_row_date(previous_row[0])

    if current_date != target_date:
        return [], []

    if current_row[1:] != previous_row[1:]:
        return [], []

    review_reasons = _row_manual_review_reasons(current_row)
    record = {
        'file': file_name,
        'date': current_date,
        'previous_date': previous_date,
        'stock_code': current_row[1],
        'type': '需人工核对' if review_reasons else '可删除重复',
        'reasons': review_reasons,
        'previous_raw': _row_to_csv_line(previous_row),
        'current_raw': _row_to_csv_line(current_row),
    }

    if record['type'] == '需人工核对':
        return [], [record]
    return [record], []


def _read_last_csv_rows(file_path, row_count=2, chunk_size=4096):
    try:
        with open(file_path, 'rb') as file:
            file.seek(0, os.SEEK_END)
            position = file.tell()
            buffer = b''
            lines = []

            while position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                file.seek(position)
                buffer = file.read(read_size) + buffer

                lines = [line for line in buffer.splitlines() if line.strip()]
                if len(lines) >= row_count:
                    break

        lines = [line.decode('utf-8-sig') for line in lines[-row_count:]]
        return list(csv.reader(lines))
    except Exception as e:
        logging.error(f"读取 {file_path} 尾部数据时出错: {e}")
        return []


def _normalize_csv_row(row):
    normalized_row = list(row[:len(STOCK_DATA_COLUMNS)])
    if len(normalized_row) < len(STOCK_DATA_COLUMNS):
        normalized_row.extend([''] * (len(STOCK_DATA_COLUMNS) - len(normalized_row)))
    return normalized_row


def _normalize_row_date(value):
    date_value = pd.to_datetime(value, errors='coerce')
    if pd.isna(date_value):
        return ''
    return date_value.strftime('%Y-%m-%d')


def _row_manual_review_reasons(row):
    numeric_values = [_to_float(value) for value in row[2:12]]
    reasons = []
    missing_columns = [column for column, value in zip(NUMERIC_COLUMNS, numeric_values) if value is None]
    if missing_columns:
        reasons.append(f"字段为空({','.join(missing_columns)})")

    price_values = numeric_values[0:4]
    volume_values = numeric_values[4:6]
    zero_price_columns = [
        column for column, value in zip(PRICE_COLUMNS, price_values)
        if value is not None and value == 0
    ]
    zero_volume_columns = [
        column for column, value in zip(ZERO_LIKE_COLUMNS, volume_values)
        if value is not None and value == 0
    ]

    if zero_price_columns:
        reasons.append(f"价格字段为0({','.join(zero_price_columns)})")
    if zero_volume_columns:
        reasons.append(f"成交字段为0({','.join(zero_volume_columns)})")

    return reasons


def _to_float(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _row_to_csv_line(row):
    output = io.StringIO()
    writer = csv.writer(output, lineterminator='')
    writer.writerow(row)
    return output.getvalue()


def _delete_latest_row_from_csv(file_path, target_date, chunk_size=4096):
    """
    今日快速清理专用：确认最后一条非空记录是target_date后，直接截断最后一行。
    避免对每个命中文件整文件读取、过滤、重写。
    """
    try:
        with open(file_path, 'rb+') as file:
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            if file_size == 0:
                return False

            buffer = b''
            position = file_size
            while position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                file.seek(position)
                buffer = file.read(read_size) + buffer

                result = _locate_last_non_empty_line(buffer, position)
                if result is not None:
                    line_start, _, line_bytes = result
                    line_text = line_bytes.decode('utf-8-sig')
                    row = next(csv.reader([line_text]))
                    row_date = _normalize_row_date(row[0]) if row else ''
                    if row_date != target_date:
                        return False

                    truncate_position = line_start
                    if line_start > 0:
                        file.seek(line_start - 1)
                        previous_byte = file.read(1)
                        if previous_byte == b'\r':
                            truncate_position = line_start - 1

                    file.truncate(truncate_position)
                    return True

        return False
    except Exception as e:
        logging.error(f"截断删除 {file_path} 最后一行时出错: {e}")
        return False


def _locate_last_non_empty_line(buffer, buffer_start):
    stripped_end = len(buffer)
    while stripped_end > 0 and buffer[stripped_end - 1:stripped_end] in (b'\n', b'\r', b' ', b'\t'):
        stripped_end -= 1

    if stripped_end == 0:
        return None

    line_start = buffer.rfind(b'\n', 0, stripped_end) + 1
    if line_start == 0 and buffer_start > 0:
        return None

    line_bytes = buffer[line_start:stripped_end]
    if line_bytes:
        return buffer_start + line_start, buffer_start + stripped_end, line_bytes

    return None


def _delete_dates_from_csv(file_path, deleted_dates):
    try:
        with open(file_path, 'r', encoding='utf-8-sig', newline='') as file:
            lines = file.readlines()

        kept_lines = []
        deleted_count = 0
        for line in lines:
            if not line.strip():
                kept_lines.append(line)
                continue
            row = next(csv.reader([line]))
            row_date = _normalize_row_date(row[0]) if row else ''
            if row_date in deleted_dates:
                deleted_count += 1
                continue
            kept_lines.append(line)

        if deleted_count == 0:
            return False

        with open(file_path, 'w', encoding='utf-8', newline='') as file:
            file.writelines(kept_lines)
        return True
    except Exception as e:
        logging.error(f"删除 {file_path} 指定日期数据时出错: {e}")
        return False


def _find_duplicate_rows(df, clean_today_only, target_date):
    compare_columns = [column for column in STOCK_DATA_COLUMNS if column != '日期']
    current_values = df[compare_columns].astype(object)
    previous_values = current_values.shift().astype(object)
    duplicate_mask = current_values.fillna('__NA__').eq(previous_values.fillna('__NA__')).all(axis=1)

    if clean_today_only:
        duplicate_mask &= df['日期文本'].eq(target_date)

    return duplicate_mask


def _manual_review_reasons(row):
    """
    停牌或接口空行情常见特征：
    1. 核心行情字段为空；
    2. 成交量、成交额为空或为0；
    3. 开高低收等价格字段出现0。
    """
    numeric_values = row[NUMERIC_COLUMNS]
    reasons = []
    missing_columns = numeric_values[numeric_values.isna()].index.tolist()
    price_values = row[PRICE_COLUMNS]
    zero_like_values = row[ZERO_LIKE_COLUMNS]
    zero_price_columns = price_values[price_values.eq(0)].index.tolist()
    zero_volume_columns = zero_like_values[zero_like_values.eq(0)].index.tolist()

    if missing_columns:
        reasons.append(f"字段为空({','.join(missing_columns)})")
    if zero_price_columns:
        reasons.append(f"价格字段为0({','.join(zero_price_columns)})")
    if zero_volume_columns:
        reasons.append(f"成交字段为0({','.join(zero_volume_columns)})")

    return reasons


def _build_records(rows, df, file_name, record_type):
    records = []
    for index, row in rows.iterrows():
        previous_date = df.loc[index - 1, '日期文本'] if index > 0 else ''
        records.append({
            'file': file_name,
            'date': row['日期文本'],
            'previous_date': previous_date,
            'stock_code': row['股票代码'],
            'type': record_type,
            'reasons': row['人工核对原因'].split('，') if row.get('人工核对原因', '') else [],
        })
    return records


def _write_report(report_path, action_desc, mode_desc, data_dir, total_files, duplicate_records, review_records,
                  cleaned_files, delete, include_raw_rows):
    parent_dir = os.path.dirname(report_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    lines = [
        'A股重复行情数据清理报告',
        f'生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        f'执行动作: {action_desc}',
        f'扫描范围: {mode_desc}',
        f'数据目录: {data_dir}',
        f'扫描CSV数量: {total_files}',
        f'可删除重复: {len(_group_records_by_file(duplicate_records))} 个文件，{len(duplicate_records)} 条记录',
        f'需人工核对: {len(_group_records_by_file(review_records))} 个文件，{len(review_records)} 条记录',
    ]

    if delete:
        lines.append(f'实际清理文件数: {cleaned_files}')
        lines.append('说明: 需人工核对记录不会被自动删除。')
    else:
        lines.append('说明: 当前为扫描模式，未执行删除。')

    # 人工核对内容放前面，优先处理不能自动删除的异常形态。
    lines.extend(_format_manual_review_summary(review_records))
    lines.append('')
    lines.extend(_format_grouped_records('需人工核对', review_records, include_raw_rows=include_raw_rows))
    lines.append('')
    lines.extend(_format_grouped_records('可删除重复', duplicate_records, include_raw_rows=False))

    with open(report_path, 'w', encoding='utf-8') as file:
        file.write('\n'.join(lines) + '\n')


def _format_grouped_records(title, records, include_raw_rows=False):
    grouped_records = _group_records_by_file(records)
    lines = [f'[{title}]']
    if not grouped_records:
        lines.append('无')
        return lines

    for file_name, file_records in grouped_records.items():
        lines.append(f'- {file_name}')
        for record in file_records:
            lines.append(f"  {record['date']} 与前一交易日 {record['previous_date']} 重复")
            if include_raw_rows and record.get('previous_raw') and record.get('current_raw'):
                lines.append(f"    # {record['previous_raw']}")
                lines.append(f"    # {record['current_raw']}")
    return lines


def _format_manual_review_summary(records):
    lines = ['[需人工核对原因分类]']
    if not records:
        lines.append('无')
        return lines

    reason_groups = {}
    for record in records:
        for reason in record.get('reasons') or ['未分类原因']:
            reason_groups.setdefault(reason, set()).add(record['file'])

    for reason, files in reason_groups.items():
        lines.append(f'- {reason}: {len(files)} 个文件')
        for file_name in sorted(files):
            lines.append(f'  {file_name}')
    return lines


def _group_records_by_file(records):
    grouped_records = {}
    for record in records:
        grouped_records.setdefault(record['file'], []).append(record)
    return grouped_records

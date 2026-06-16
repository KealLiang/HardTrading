#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
扫描 ./data/astocks 下损坏的日线 CSV。

常见损坏类型（多因写入中断、意外断电/重启导致）：
  - null_bytes: 文件内容全为 \\x00（重写 to_csv 时被截断）
  - empty: 0 字节空文件
  - no_valid_rows: 能解析但无有效日期行（含 NUL 污染等）
  - single_row: 仅 1 条有效日线（写入中断后的兜底覆盖）
  - parse_error: 无法按标准列解析

用法:
  conda activate trading
  python tests/check_corrupted_stock_csvs.py
  python tests/check_corrupted_stock_csvs.py --repair-codes   # 仅输出待修复股票代码
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pandas as pd

# 项目根目录
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fetch.astock_data_cleaner import STOCK_DATA_COLUMNS

STOCK_CODE_RE = re.compile(r'^(\d{6})_')
SKIP_FILES = {'stock_mapping.csv'}


@dataclass
class CorruptEntry:
    filename: str
    stock_code: str
    reason: str
    size: int
    valid_rows: Optional[int] = None
    detail: str = ''


@dataclass
class ScanResult:
    total: int = 0
    ok: int = 0
    corrupted: List[CorruptEntry] = field(default_factory=list)

    def by_reason(self) -> dict:
        groups: dict[str, List[CorruptEntry]] = {}
        for item in self.corrupted:
            groups.setdefault(item.reason, []).append(item)
        return groups


def _extract_code(filename: str) -> Optional[str]:
    m = STOCK_CODE_RE.match(filename)
    return m.group(1) if m else None


def _is_all_null_bytes(file_path: Path) -> bool:
    size = file_path.stat().st_size
    if size == 0:
        return False
    with file_path.open('rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                return True
            if any(b != 0 for b in chunk):
                return False


def scan_corrupted_stock_csvs(
    save_path: str | Path = './data/astocks',
    min_valid_rows: int = 2,
) -> ScanResult:
    """
    扫描损坏 CSV。min_valid_rows=2 表示至少需 2 条有效日线才算正常（start_date 自 20250930）。
    """
    save_dir = Path(save_path)
    result = ScanResult()

    if not save_dir.is_dir():
        raise FileNotFoundError(f"目录不存在: {save_dir}")

    for file_path in sorted(save_dir.glob('*.csv')):
        filename = file_path.name
        if filename in SKIP_FILES:
            continue

        result.total += 1
        code = _extract_code(filename) or ''
        size = file_path.stat().st_size

        if size == 0:
            result.corrupted.append(CorruptEntry(filename, code, 'empty', size))
            continue

        if _is_all_null_bytes(file_path):
            result.corrupted.append(
                CorruptEntry(filename, code, 'null_bytes', size, detail='文件内容全为 NUL 字节')
            )
            continue

        try:
            df = pd.read_csv(
                file_path,
                header=None,
                names=STOCK_DATA_COLUMNS,
                dtype={'股票代码': str},
            )
            valid = df[~df['日期'].isna()]
            valid_count = len(valid)

            if valid_count == 0:
                result.corrupted.append(
                    CorruptEntry(
                        filename, code, 'no_valid_rows', size, valid_count,
                        '可解析但无有效日期行',
                    )
                )
            elif valid_count < min_valid_rows:
                result.corrupted.append(
                    CorruptEntry(
                        filename, code, 'single_row', size, valid_count,
                        f'有效日线仅 {valid_count} 行',
                    )
                )
            else:
                result.ok += 1
        except Exception as exc:
            result.corrupted.append(
                CorruptEntry(filename, code, 'parse_error', size, detail=str(exc)[:120])
            )

    return result


def _print_report(result: ScanResult, report_path: Optional[Path]) -> None:
    groups = result.by_reason()
    lines: List[str] = []

    lines.append('=' * 60)
    lines.append('A股日线 CSV 损坏扫描报告')
    lines.append('=' * 60)
    lines.append(f'扫描文件数: {result.total}')
    lines.append(f'正常文件数: {result.ok}')
    lines.append(f'损坏文件数: {len(result.corrupted)}')
    lines.append('')

    reason_labels = {
        'null_bytes': '全 NUL 字节（写入中断，数据不可从文件恢复）',
        'empty': '空文件（0 字节）',
        'no_valid_rows': '无有效日期行',
        'single_row': '仅 1 条有效日线（残缺）',
        'parse_error': '解析失败',
    }

    for reason, label in reason_labels.items():
        items = groups.get(reason, [])
        if not items:
            continue
        lines.append(f'--- {label} ({len(items)}) ---')
        for item in items:
            extra = f', {item.detail}' if item.detail else ''
            if item.valid_rows is not None:
                extra = f', valid_rows={item.valid_rows}{extra}'
            lines.append(f'  {item.filename}  code={item.stock_code}  size={item.size}{extra}')
        lines.append('')

    repair_codes = sorted({e.stock_code for e in result.corrupted if e.stock_code})
    if repair_codes:
        lines.append(f'待修复股票代码 ({len(repair_codes)} 只):')
        lines.append(','.join(repair_codes))
        lines.append('')
        lines.append('修复建议: 在 main.py 中调用')
        lines.append('  repair_truncated_stock_datas(stock_list=[...])')
        lines.append('或将上述代码保存后执行:')
        lines.append('  from main import repair_truncated_stock_datas')
        lines.append(f'  repair_truncated_stock_datas(stock_list={repair_codes[:3]}...)')

    text = '\n'.join(lines)
    print(text)

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding='utf-8')
        print(f'\n报告已保存: {report_path}')


def main() -> None:
    parser = argparse.ArgumentParser(description='检测损坏的 A 股日线 CSV')
    parser.add_argument(
        '--data-dir', default=str(ROOT / 'data' / 'astocks'), help='CSV 目录，默认 data/astocks'
    )
    parser.add_argument(
        '--report', default=str(ROOT / 'data' / 'astocks_corrupt_scan_report.txt'),
        help='报告输出路径，传空字符串则不写文件',
    )
    parser.add_argument(
        '--repair-codes', action='store_true', help='仅输出待修复股票代码（逗号分隔）',
    )
    args = parser.parse_args()

    result = scan_corrupted_stock_csvs(args.data_dir)
    repair_codes = sorted({e.stock_code for e in result.corrupted if e.stock_code})

    if args.repair_codes:
        print(','.join(repair_codes))
        return

    report_path = Path(args.report) if args.report else None
    _print_report(result, report_path)


if __name__ == '__main__':
    main()

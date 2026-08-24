"""Write filings/holdings Parquet with an explicit Arrow schema. No pandas."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

FILINGS_SCHEMA = pa.schema(
    [
        pa.field("accession_number", pa.string(), nullable=False),
        pa.field("cik", pa.string(), nullable=False),
        pa.field("fund_name", pa.string(), nullable=False),
        pa.field("filing_manager", pa.string(), nullable=False),
        pa.field("form_type", pa.string(), nullable=False),
        pa.field("report_period", pa.date32(), nullable=False),
        pa.field("report_quarter", pa.string(), nullable=False),
        pa.field("filing_date", pa.date32(), nullable=False),
        pa.field("is_amendment", pa.bool_(), nullable=False),
        pa.field("amendment_no", pa.int32(), nullable=True),
        pa.field("amendment_type", pa.string(), nullable=True),
        pa.field("report_type", pa.string(), nullable=False),
        pa.field("form_13f_file_number", pa.string(), nullable=True),
        pa.field("crd_number", pa.string(), nullable=True),
        pa.field("sec_file_number", pa.string(), nullable=True),
        pa.field("other_included_managers_count", pa.int32(), nullable=True),
        pa.field("table_entry_total", pa.int64(), nullable=True),
        pa.field("table_value_total", pa.int64(), nullable=True),
    ]
)

HOLDINGS_SCHEMA = pa.schema(
    [
        pa.field("accession_number", pa.string(), nullable=False),
        pa.field("cik", pa.string(), nullable=False),
        pa.field("report_quarter", pa.string(), nullable=False),
        pa.field("name_of_issuer", pa.string(), nullable=False),
        pa.field("title_of_class", pa.string(), nullable=False),
        pa.field("cusip", pa.string(), nullable=False),
        pa.field("figi", pa.string(), nullable=True),
        pa.field("value", pa.int64(), nullable=False),
        pa.field("ssh_prnamt", pa.int64(), nullable=False),
        pa.field("ssh_prnamt_type", pa.string(), nullable=False),
        pa.field("put_call", pa.string(), nullable=True),
        pa.field("investment_discretion", pa.string(), nullable=False),
        pa.field("other_manager", pa.string(), nullable=True),
        pa.field("voting_sole", pa.int64(), nullable=False),
        pa.field("voting_shared", pa.int64(), nullable=False),
        pa.field("voting_none", pa.int64(), nullable=False),
    ]
)


def _column(rows: list[dict[str, Any]], name: str, type_: pa.DataType) -> pa.Array:
    return pa.array([row.get(name) for row in rows], type=type_)


def table_from_rows(rows: list[dict[str, Any]], schema: pa.Schema) -> pa.Table:
    if not rows:
        return pa.Table.from_arrays(
            [pa.array([], type=f.type) for f in schema], schema=schema
        )
    arrays = [_column(rows, f.name, f.type) for f in schema]
    return pa.Table.from_arrays(arrays, schema=schema)


def write_parquet(
    output: Path,
    filings_rows: list[dict[str, Any]],
    holdings_rows: list[dict[str, Any]],
) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    filings_path = output / "filings.parquet"
    holdings_path = output / "holdings.parquet"
    filings = table_from_rows(filings_rows, FILINGS_SCHEMA)
    holdings = table_from_rows(holdings_rows, HOLDINGS_SCHEMA)
    pq.write_table(filings, filings_path, compression="snappy")
    pq.write_table(holdings, holdings_path, compression="snappy")
    return filings_path, holdings_path


ATTRIBUTED_SCHEMA = pa.schema(
    list(HOLDINGS_SCHEMA) + [pa.field("attributed_to_cik", pa.string(), nullable=False)]
)


def write_attributed_parquet(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = table_from_rows(rows, ATTRIBUTED_SCHEMA)
    pq.write_table(table, path, compression="snappy")
    return path

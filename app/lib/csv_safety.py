"""Guards for CSV files people open in a spreadsheet."""


def excel_safe_text(value) -> str:
    """Stop a spreadsheet treating user-written text as a formula.

    Exports are served with a UTF-8 BOM so Excel opens them. A cell starting
    with ``=``, ``+``, ``-``, ``@``, tab, or CR would run.
    """
    text = '' if value is None else str(value)
    if text[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + text
    return text

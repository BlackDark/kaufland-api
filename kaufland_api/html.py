"""Printable receipt HTML built from the Kaufland transaction JSON."""

import html


def money(value):
    if isinstance(value, str):
        value = value.replace(",", ".")
    try:
        minor = int(value)
    except TypeError, ValueError:
        return ""
    sign = "-" if minor < 0 else ""
    whole, frac = f"{abs(minor) / 100:.2f}".split(".")
    return f"{sign}{whole},{frac}"


def _esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def _rows(positions):
    lines = []
    for position in positions or []:
        if not isinstance(position, dict):
            continue
        name = _esc(position.get("name") or position.get("description") or "Artikel")
        quantity = position.get("quantity", 1)
        unit = position.get("quantityUnit") or ""
        qty = _esc(quantity)
        if unit:
            qty = f"{qty} {_esc(unit)}"
        unit_price = money(position.get("unitPrice"))
        total = money(
            position.get("total", position.get("price", position.get("amount")))
        )
        price = f"{_esc(unit_price)} × " if unit_price else ""
        lines.append(
            f"<tr><td>{name}<div class='meta'>{price}{qty}</div></td>"
            f"<td class='amount'>{_esc(total)}</td></tr>"
        )
    return "\n".join(lines)


def _store_lines(detail):
    store = detail.get("store") if isinstance(detail.get("store"), dict) else {}
    parts = [
        store.get("name") or "Kaufland",
        " ".join(str(part) for part in (store.get("zip"), store.get("city")) if part),
        store.get("street"),
    ]
    return "<br>".join(_esc(part) for part in parts if part)


def receipt_html(detail, *, refund=False):
    """One purchase document, or the refund positions as their own document."""
    positions = detail.get("refundPositions") if refund else detail.get("positions")
    title = "Retoure" if refund else "Kassenbon"
    when = detail.get("timestamp") or detail.get("date") or ""
    currency = detail.get("currency") or "EUR"
    extras = []
    if not refund:
        for label, key in (("Summe", "sum"), ("Ersparnis", "saving")):
            if detail.get(key) is not None:
                extras.append(
                    f"<tr><td>{label}</td><td class='amount'>{_esc(money(detail.get(key)))}</td></tr>"
                )
        points = detail.get("bonusPoints")
        if points not in (None, "", 0, "0"):
            extras.append(
                f"<tr><td>Bonuspunkte</td><td class='amount'>{_esc(points)}</td></tr>"
            )
        payment = detail.get("paymentType")
        if payment:
            extras.append(
                f"<tr><td>Zahlung</td><td class='amount'>{_esc(payment)}</td></tr>"
            )
    taxes = detail.get("taxes") if isinstance(detail.get("taxes"), list) else []
    tax_rows = []
    for tax in taxes:
        if isinstance(tax, dict):
            rate = tax.get("taxRate") or tax.get("rate") or tax.get("taxClass") or ""
            amount = money(tax.get("amount") or tax.get("value") or tax.get("sum"))
            if rate or amount:
                tax_rows.append(
                    f"<tr><td>MwSt {_esc(rate)}</td><td class='amount'>{_esc(amount)}</td></tr>"
                )
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>{title}</title>
<style>
body {{ font-family: ui-monospace, monospace; width: 420px; margin: 16px; color: #111; }}
h1 {{ font-size: 18px; margin: 0 0 8px; }}
.meta {{ color: #444; font-size: 12px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
td {{ vertical-align: top; padding: 4px 0; border-bottom: 1px solid #ddd; }}
.amount {{ text-align: right; white-space: nowrap; }}
</style></head><body>
<h1>{title}</h1>
<p>{_store_lines(detail)}<br>{_esc(when)}<br>{_esc(currency)} · {_esc(detail.get("id"))}</p>
<table>{_rows(positions)}{"".join(extras)}{"".join(tax_rows)}</table>
</body></html>"""


def printable_documents(detail):
    source = detail.get("htmlPrintedReceipt")
    if isinstance(source, str) and source.strip():
        documents = [source]
        for extra in detail.get("returnedHtmlTickets") or []:
            html_source = (
                extra.get("htmlPrintedReceipt") if isinstance(extra, dict) else None
            )
            if isinstance(html_source, str) and html_source.strip():
                documents.append(html_source)
        return documents
    documents = [receipt_html(detail)]
    if detail.get("refundPositions"):
        documents.append(receipt_html(detail, refund=True))
    return documents

"""
Trim PDF to a maximum number of pages.

POST /api/trim_pdf
Request  : { "fileContent": "<base64 PDF>", "maxPages": 50, "strategy": "first" }
Response : { "originalPageCount": 120, "returnedPageCount": 50,
             "truncated": true, "fileContent": "<base64 PDF>" }

strategy:
  "first"        keep pages 1..maxPages                (default)
  "first_last"   keep first (maxPages-10) + last 10    (keeps signature pages)
"""
import base64
import io
import json
import logging

import azure.functions as func
from pypdf import PdfReader, PdfWriter

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

TAIL_PAGES = 10


def _pages_to_keep(total: int, max_pages: int, strategy: str):
    if total <= max_pages:
        return list(range(total))
    if strategy == "first_last" and max_pages > TAIL_PAGES:
        head = max_pages - TAIL_PAGES
        return list(range(head)) + list(range(total - TAIL_PAGES, total))
    return list(range(max_pages))


def trim_pdf_bytes(data: bytes, max_pages: int, strategy: str = "first") -> dict:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        # Owner-password-only PDFs open with an empty user password.
        if not reader.decrypt(""):
            raise ValueError("PDF is password protected")
    total = len(reader.pages)
    keep = _pages_to_keep(total, max_pages, strategy)

    if total <= max_pages:  # pass through untouched - no re-write risk
        return {
            "originalPageCount": total,
            "returnedPageCount": total,
            "truncated": False,
            "fileContent": base64.b64encode(data).decode("ascii"),
        }

    writer = PdfWriter()
    for i in keep:
        writer.add_page(reader.pages[i])
    out = io.BytesIO()
    writer.write(out)
    return {
        "originalPageCount": total,
        "returnedPageCount": len(keep),
        "truncated": True,
        "fileContent": base64.b64encode(out.getvalue()).decode("ascii"),
    }


@app.route(route="trim_pdf", methods=["POST"])
def trim_pdf(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
        raw = body["fileContent"]
        max_pages = int(body.get("maxPages", 50))
        strategy = body.get("strategy", "first")
        if max_pages < 1:
            raise ValueError("maxPages must be >= 1")
        result = trim_pdf_bytes(base64.b64decode(raw), max_pages, strategy)
        return func.HttpResponse(json.dumps(result), mimetype="application/json")
    except Exception as exc:  # surfaced to the flow as a 400 -> failure email
        logging.exception("trim_pdf failed")
        return func.HttpResponse(json.dumps({"error": str(exc)}), status_code=400,
                                 mimetype="application/json")

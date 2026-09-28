"""Drive file + converted body → the worker pipeline's event shape."""
from __future__ import annotations

from ghostbrain.connectors.gdrive import drive
from ghostbrain.connectors.gdrive.convert import ConvertResult

TYPE_BY_MIME = {
    drive.GDOC: "doc", drive.GSHEET: "sheet", drive.PDF: "pdf",
    drive.DOCX: "docx", drive.XLSX: "xlsx",
}


def build_event(file: dict, *, account: str, result: ConvertResult, folder: str | None) -> dict:
    url = file.get("webViewLink")
    links = " · ".join(x for x in (f"[Open in Drive]({url})" if url else "", folder or "") if x)
    body = f"# {file['name']}\n\n" + (f"{links}\n\n" if links else "") + result.body
    modifier = (file.get("lastModifyingUser") or {}).get("emailAddress") or "?"
    return {
        "id": f"gdrive:{file['id']}",
        "source": "gdrive",
        "type": TYPE_BY_MIME[file["mimeType"]],
        "subtype": "updated",
        "timestamp": file["modifiedTime"],
        "title": file["name"],
        "url": url,
        "actorId": f"gdrive:{modifier}",
        "body": body,
        "metadata": {
            "accountId": account,
            "fileId": file["id"],
            "mimeType": file["mimeType"],
            "driveModifiedTime": file["modifiedTime"],
            "owners": [o["emailAddress"] for o in file.get("owners") or [] if o.get("emailAddress")],
            "folder": folder,
            "truncated": result.truncated,
        },
    }

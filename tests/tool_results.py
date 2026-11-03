"""Unpack the image tools' CallToolResult the way a client sees it."""
import base64


def unpack(result):
    """(PNG bytes or None, notes text, structured result)."""
    image = next((base64.b64decode(c.data) for c in result.content if c.type == "image"), None)
    structured = result.structured_content
    return image, structured.get("notes", ""), structured

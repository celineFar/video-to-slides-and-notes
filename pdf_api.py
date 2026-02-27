from PyPDF2 import PdfMerger
from typing import List
import os
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.colors import HexColor
from PIL import Image



def merge_pdfs(input_paths: List[str], output_path: str) -> str:
    """
    Merge a list of PDF files into a single PDF.

    Args:
        input_paths: List of file paths to the PDFs to merge, in order.
        output_path: File path where the merged PDF should be written.

    Returns:
        The output_path of the merged PDF.
    """
    merger = PdfMerger()
    try:
        for pdf_path in input_paths:
            # You can pass a bookmark name here as a second arg if you want
            merger.append(pdf_path)
        # Write out the merged PDF
        with open(output_path, 'wb') as f_out:
            merger.write(f_out)
    finally:
        merger.close()
    return output_path


def wrap_text(text: str, font_name: str, font_size: int, max_width: float):
    lines = []
    for paragraph in text.splitlines():
        words = paragraph.split()
        if not words:
            lines.append("")
            continue

        wrapped_line = ""
        for word in words:
            test_line = wrapped_line + (" " if wrapped_line else "") + word
            if pdfmetrics.stringWidth(test_line, font_name, font_size) <= max_width:
                wrapped_line = test_line
            else:
                if wrapped_line:
                    lines.append(wrapped_line)
                wrapped_line = word
        if wrapped_line:
            lines.append(wrapped_line)
    return lines


def image_to_pdf(
    image_path: str,
    caption: str,
    output_path: str,
    margin: float = 40,
    font_size: int = 62,
    line_spacing: int = 2,
    caption_position: str = "above"
) -> str:
    """
    Generate a single-page PDF containing the given image (full size)
    and the caption text either above or below the image.
    Set caption_position to "above" (default) or "below".
    Returns the path to the created PDF.
    """
    # Load image and measure
    img = Image.open(image_path)
    img_w, img_h = img.size

    # Wrap caption text to image width
    lines = wrap_text(caption, "Helvetica", font_size, img_w)
    line_height = font_size + line_spacing
    transcript_block_h = len(lines) * line_height

    # Determine page size and positions based on caption position
    if caption_position.lower() == "above":
        page_w = img_w + 2 * margin
        page_h = margin + transcript_block_h + margin + img_h + margin
        # Caption at top, image at bottom
        text_y_start = page_h - margin - line_height
        x_img = margin
        y_img = margin
    elif caption_position.lower() == "below":
        page_w = img_w + 2 * margin
        page_h = margin + img_h + margin + transcript_block_h + margin
        # Image at top, caption at bottom
        x_img = margin
        y_img = page_h - margin - img_h
        text_y_start = margin + transcript_block_h - line_height
    else:
        raise ValueError("caption_position must be 'above' or 'below'")

    # Create canvas
    c = canvas.Canvas(output_path, pagesize=(page_w, page_h))
    c.setFillColor(HexColor("#333333"))
    c.setFont("Helvetica", font_size)

    # === DEBUG VISUALS (optional) ===
    # c.setStrokeColor(HexColor("#FF0000"))
    # c.rect(0, 0, page_w, page_h)

    # Draw caption lines
    max_line_width = max((pdfmetrics.stringWidth(line, "Helvetica", font_size)
                          for line in lines), default=0)
    block_x = (page_w - max_line_width) / 2
    for i, line in enumerate(lines):
        if caption_position.lower() == "above":
            y = text_y_start - i * line_height
        else:
            y = text_y_start - i * line_height
        c.drawString(block_x, y, line)

    # Draw image
    c.drawImage(image_path, x_img, y_img, width=img_w, height=img_h,
                preserveAspectRatio=True)

    c.showPage()
    c.save()

    return output_path

#!/usr/bin/env python3
"""Generate realistic PDF source data for the RAG workshop.

WHY THIS SCRIPT EXISTS
----------------------
The workshop demonstrates a RAG pipeline over policy PDFs (employee handbook,
expense policy, security policy, etc.). To keep dependencies minimal we do
NOT use ReportLab, FPDF, or any other PDF library. Instead, this file emits
PDF bytes directly using the PDF 1.4 file format.

That makes the script self-contained — a fresh Python install with no extra
pip dependencies can still produce all six policy PDFs.

PDF FILE STRUCTURE PRIMER
-------------------------
A PDF is a list of numbered "objects" plus a cross-reference table that maps
each object number to its byte offset in the file. The minimum objects we
emit per document:

  1. Catalog       (the document root, points to the pages tree)
  2. Pages         (the parent of all page objects)
  3. Font          (Helvetica, a built-in PDF font, requires no embedding)
  4..N. Alternating "content stream" and "page" objects:
        - a content stream describes the text drawing commands for one page
        - a page object references the stream and the font

Followed by:

  - xref table     (byte offset of each object in the file)
  - trailer        (points at the catalog and xref start)
  - %%EOF          (end-of-file marker)
"""

from __future__ import annotations

# `textwrap.wrap` is used to break long paragraphs into lines that fit on
# the page. `Path` handles the output directory and file paths.
import textwrap
from pathlib import Path


# All generated PDFs land in this directory. It is created on demand.
OUTPUT_DIR = Path("data/generated_pdfs")

# Page geometry: 612x792 points is US Letter (8.5"x11" * 72 dpi).
PAGE_WIDTH = 612
PAGE_HEIGHT = 792
# Left margin in points (about 0.75 inch).
LEFT_MARGIN = 54
# Y coordinate of the top text baseline. PDF coordinates start at the
# bottom-left, so a high Y is near the top of the page.
TOP_Y = 744
# Vertical distance between consecutive text lines.
LINE_HEIGHT = 14
# Number of lines we draw per page before forcing a page break.
LINES_PER_PAGE = 48


# Every key in this dict becomes a generated PDF file. The body text is
# written to read like real internal policy content so the RAG demo has
# meaningful question/answer behavior at retrieval time.
POLICIES = {
    "employee-handbook.pdf": {
        "title": "Aster Analytics Employee Handbook",
        "sections": [
            ("Purpose", "This handbook explains the employment standards used by Aster Analytics. It applies to regular full-time and part-time employees unless a signed employment contract states otherwise."),
            ("Working Hours", "The standard work week is Monday through Friday. Full-time employees are expected to work 40 hours per week. Managers may approve flexible schedules when business coverage and customer commitments are maintained."),
            ("Paid Annual Leave", "Full-time employees receive 20 paid annual leave days per calendar year. Part-time employees accrue leave on a prorated basis. Employees should request leave at least 10 business days in advance when possible."),
            ("Sick Leave", "Employees receive 10 paid sick leave days per calendar year. Sick leave may be used for personal illness, medical appointments, or caring for an immediate family member."),
            ("Code of Conduct", "Employees must act honestly, protect confidential information, avoid conflicts of interest, and follow all applicable laws. Suspected violations should be reported to People Operations or Legal."),
            ("Performance Reviews", "Formal performance reviews occur twice each year. Managers may also hold quarterly check-ins to discuss goals, feedback, and development plans."),
        ],
    },
    "travel-expense-policy.pdf": {
        "title": "Travel and Expense Reimbursement Policy",
        "sections": [
            ("Purpose", "This policy defines reimbursable business travel expenses and the approval process for Aster Analytics employees."),
            ("Air Travel", "Employees should book economy class for domestic flights. Premium economy may be approved for international flights longer than six hours. Business class requires executive approval before booking."),
            ("Hotels", "The domestic hotel reimbursement limit is USD 220 per night before taxes. The international hotel reimbursement limit is USD 310 per night before taxes. Exceptions require manager and Finance approval."),
            ("Meals", "Meal reimbursement is limited to USD 75 per day for domestic travel and USD 95 per day for international travel. Alcohol is not reimbursable unless part of an approved customer event."),
            ("Ground Transportation", "Employees should use rideshare, taxi, public transit, or rental cars when reasonable. Luxury vehicle classes are not reimbursable."),
            ("Expense Reports", "Expense reports must be submitted within 30 days of trip completion. Receipts are required for any single expense greater than USD 25."),
        ],
    },
    "it-security-policy.pdf": {
        "title": "Information Security Policy",
        "sections": [
            ("Purpose", "This policy protects company systems, customer data, and employee information from unauthorized access or disclosure."),
            ("Passwords and MFA", "Employees must use unique passwords and multi-factor authentication for company systems. Passwords must not be reused across personal and company accounts."),
            ("Personal Devices", "Personal devices may be used for company work only when enrolled in the approved mobile device management program. Devices must use disk encryption, screen lock, and remote wipe capability."),
            ("Data Classification", "Company data is classified as Public, Internal, Confidential, or Restricted. Customer records, financial forecasts, security keys, and employee health information are Restricted."),
            ("Incident Reporting", "Lost devices, suspicious emails, accidental disclosure, or suspected compromise must be reported to Security within one hour of discovery."),
            ("AI Tool Usage", "Employees must not paste Restricted data, secrets, access tokens, or customer confidential information into external AI tools unless Legal and Security have approved the tool and data use case."),
        ],
    },
    "remote-work-policy.pdf": {
        "title": "Remote and Hybrid Work Policy",
        "sections": [
            ("Purpose", "This policy defines how employees may work remotely while maintaining collaboration, security, and customer responsiveness."),
            ("Eligibility", "Employees in roles that do not require physical presence may request remote or hybrid work. Approval depends on role duties, performance, team coverage, and local legal requirements."),
            ("Core Collaboration Hours", "Employees must be available during core collaboration hours from 10:00 AM to 3:00 PM in their assigned office time zone unless their manager approves an exception."),
            ("Home Office", "Employees are responsible for a safe and reliable workspace. The company reimburses up to USD 500 for approved home office equipment once every three years."),
            ("Location Changes", "Employees who plan to work from another state or country for more than 15 business days must obtain People Operations and Tax approval before the location change."),
            ("Security", "Remote employees must use company-approved VPN where required, avoid public Wi-Fi without protection, and follow the Information Security Policy."),
        ],
    },
    "procurement-policy.pdf": {
        "title": "Procurement and Vendor Management Policy",
        "sections": [
            ("Purpose", "This policy ensures that purchases are approved, cost effective, secure, and aligned with company budget controls."),
            ("Purchase Requests", "Employees must create a purchase request before committing company funds. The request must include business justification, vendor name, estimated cost, and budget owner."),
            ("Approval Thresholds", "Purchases up to USD 1,000 require manager approval. Purchases from USD 1,001 to USD 5,000 require manager and budget owner approval. Purchases above USD 5,000 require manager, budget owner, and Finance approval."),
            ("Security Review", "Any vendor that stores, processes, or accesses company or customer data requires Security review before contract signature."),
            ("Legal Review", "Any new vendor contract, renewal with changed terms, or agreement containing indemnity, data processing, or auto-renewal clauses requires Legal review."),
            ("Preferred Vendors", "Employees should use preferred vendors where available. Exceptions must document why the preferred vendor cannot meet the business need."),
        ],
    },
    "onboarding-guide.pdf": {
        "title": "New Employee Onboarding Guide",
        "sections": [
            ("Day One", "New employees complete identity verification, payroll forms, security training, and device setup on the first day."),
            ("First Week", "During the first week, employees meet their manager, review team goals, complete required compliance training, and confirm system access."),
            ("First 30 Days", "Managers should define role expectations, assign an onboarding buddy, and agree on the first 30-day success outcomes."),
            ("Required Training", "Required training includes information security, code of conduct, data privacy, anti-harassment, and expense policy training."),
            ("Access Requests", "Access to production systems requires manager approval and completion of security training. Privileged access requires Security approval."),
            ("Support", "Employees may contact People Operations for HR questions, IT Support for device issues, and Finance for payroll or expense questions."),
        ],
    },
}


def escape_pdf_text(value: str) -> str:
    """Escape characters that have special meaning inside PDF text strings.

    Inside a PDF `(...)` text literal, backslash and parentheses must be
    escaped or the parser will treat them as syntax tokens and corrupt the
    document.
    """
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def wrap_lines(title: str, sections: list[tuple[str, str]]) -> list[str]:
    """Convert a document title and sections into wrapped text lines.

    The output is a flat list of lines that the paginator can consume. Blank
    lines are inserted between sections for visual spacing.
    """
    # Start with the document title followed by a blank line.
    lines = [title, ""]
    for heading, body in sections:
        # The section heading lives on its own line.
        lines.append(heading)
        # Wrap the body at 88 characters — picked to roughly match the page
        # width with Helvetica 10pt at the configured left margin.
        wrapped = textwrap.wrap(body, width=88)
        lines.extend(wrapped)
        # Blank line between sections.
        lines.append("")
    return lines


def paginate(lines: list[str]) -> list[list[str]]:
    """Split wrapped lines into fixed-size PDF pages.

    A simple chunking approach: `LINES_PER_PAGE` lines per page. Headings
    can occasionally land at the very bottom of a page; that's fine for a
    workshop demo and keeps this script simple.
    """
    return [lines[index : index + LINES_PER_PAGE] for index in range(0, len(lines), LINES_PER_PAGE)]


def build_page_stream(lines: list[str]) -> bytes:
    """Build a PDF content stream that draws text lines on one page.

    PDF content streams are tiny programs in a stack-based drawing language:

      BT             begin text object
      /F1 10 Tf      use font F1 at 10pt
      x y Td         move the text cursor to (x, y)
      n TL           set the leading (line height) to n
      (text) Tj      draw the literal text string
      T*             move down to the next line
      ET             end text object
    """
    commands = ["BT", "/F1 10 Tf", f"{LEFT_MARGIN} {TOP_Y} Td", f"{LINE_HEIGHT} TL"]
    for line in lines:
        # Draw the line, then move down one line height for the next one.
        commands.append(f"({escape_pdf_text(line)}) Tj")
        commands.append("T*")
    commands.append("ET")
    # PDF content streams are bytes, not text. Encode the assembled commands.
    return "\n".join(commands).encode("utf-8")


def write_pdf(path: Path, title: str, sections: list[tuple[str, str]]) -> None:
    """Write a small valid PDF file to `path`.

    A PDF is a collection of numbered objects. This function creates the
    catalog, pages tree, font object, page objects, and text stream
    objects, then writes the cross-reference table required by PDF readers.
    """
    # Turn the document content into a list of pages, each one a list of lines.
    pages = paginate(wrap_lines(title, sections))

    # `objects` collects raw PDF object bodies in order. The index in this
    # list + 1 is the PDF object number (PDF object numbering is 1-based).
    objects: list[bytes] = []

    def add_object(content: bytes) -> int:
        """Append a PDF object and return its 1-based object number."""
        objects.append(content)
        return len(objects)

    # Reserve the core PDF objects in the order PDF readers expect them:
    #   1: Catalog (root of the document tree)
    #   2: Pages  (children list filled in later, hence the empty body)
    #   3: Font   (built-in Helvetica)
    catalog_id = add_object(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add_object(b"")
    font_id = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    # Build one (content stream, page) pair per page.
    page_ids = []
    content_ids = []
    for page_lines in pages:
        stream = build_page_stream(page_lines)
        # Wrap the raw drawing program in a stream object with /Length so
        # PDF readers know how many bytes to read.
        content = b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream"
        content_ids.append(add_object(content))
        # Reserve a slot for the page object body; we fill it in next.
        page_ids.append(add_object(b""))

    # Now that we know every page object id, fill in the pages tree body
    # with `/Kids [ ... ] /Count N`.
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids).encode("ascii")
    objects[pages_id - 1] = b"<< /Type /Pages /Kids [ " + kids + b" ] /Count " + str(len(page_ids)).encode("ascii") + b" >>"

    # And fill in each page object body with a reference to its content
    # stream and the shared font. `MediaBox` sets the page size.
    for page_id, content_id in zip(page_ids, content_ids):
        objects[page_id - 1] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            + str(PAGE_WIDTH).encode("ascii")
            + b" "
            + str(PAGE_HEIGHT).encode("ascii")
            + b"] /Resources << /Font << /F1 3 0 R >> >> /Contents "
            + str(content_id).encode("ascii")
            + b" 0 R >>"
        )

    # ---- Assemble the final byte sequence ----
    #
    # 1) The PDF header line tells readers this is a PDF 1.4 file.
    pdf = bytearray(b"%PDF-1.4\n")
    # `offsets[i]` will be the byte offset of object `i`. Object 0 is the
    # special "head of the free list" entry and stays at offset 0.
    offsets = [0]

    # 2) Write each object preceded by `N 0 obj` and followed by `endobj`.
    for index, content in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(content)
        pdf.extend(b"\nendobj\n")

    # 3) Record where the xref table starts so the trailer can point at it.
    xref_start = len(pdf)

    # 4) Write the xref table. Entry 0 is always `0000000000 65535 f` (free).
    #    Every other entry is `NNNNNNNNNN 00000 n` with the 10-digit offset.
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    # 5) Write the trailer dictionary, the `startxref` pointer, and the
    #    `%%EOF` marker. PDF readers look for `startxref` near the end to
    #    locate the xref table, then walk the object graph from /Root.
    pdf.extend(
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode("ascii")
        + b" /Root "
        + str(catalog_id).encode("ascii")
        + b" 0 R >>\nstartxref\n"
        + str(xref_start).encode("ascii")
        + b"\n%%EOF\n"
    )

    # Write the final bytes to disk in one shot.
    path.write_bytes(bytes(pdf))


def main() -> None:
    """Generate every policy PDF into the configured output directory."""
    # `mkdir(parents=True, exist_ok=True)` mirrors `mkdir -p`.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, policy in POLICIES.items():
        write_pdf(OUTPUT_DIR / filename, policy["title"], policy["sections"])
        print(f"Generated {OUTPUT_DIR / filename}")


if __name__ == "__main__":
    main()

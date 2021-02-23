import re
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import pdfplumber
from PyPDF2 import PdfFileReader, PdfFileWriter
from PyPDF2.pdf import PageObject

from bankruptcy.fields import (
    make_ab_totals,
    make_car_dict,
    make_creditor_dict,
    make_other_dict,
    make_property_dict,
    make_secured_creditor_dict,
    property_options,
)
from bankruptcy.filters import (
    filter_106_ab_content,
    filter_boxes,
    input_white_text_and_left_side,
    just_text_filter,
    key_filter,
    keys_and_input_text,
    line_filter,
    remove_margin_lines,
)


def get_106_sum_pages(filepath: str) -> List:
    """Find the pages containing Form 106 Sum

    :param filepath:
    :return:
    """
    with pdfplumber.open(filepath) as pdf:
        pages = pdf.pages
        for page in pages:
            if page.extract_text()[-300:].find("Official Form 106Sum") == -1:
                continue
            return pages[page.page_number - 1 : page.page_number]


def crop_and_extract(
    page: pdfplumber.pdf.Page,
    line: Dict,
    adjust=False,
    left: int = 0,
    up: int = 20,
    down: int = 0,
    right: int = 0,
) -> str:
    """Extract text content for pdf line if any

    Given a line of a pdf - extracted the text around it.  If adjust
    is True, reduce the cropped area to within the first line (usually above)
    :param page: Page to crop
    :param line: Line to crop around
    :param adjust: Whether to check if another line is inside our crop
    :param left: Leftward crop adjustment
    :param up: Upward crop adjustment
    :param down: Downward crop adjustment
    :param right: Rightward crop adjustment
    :return: Content of the section
    """
    bbox = (
        int(line["x0"]) - left,
        int(line["top"]) - up,
        line["x1"] - right,
        line["top"] - down,
    )
    crop = page.crop(bbox)
    if adjust:
        tops = [row["top"] for row in crop.lines if row["top"] != line["top"]]
        if len(tops) > 0:
            crop = page.crop(bbox=(*bbox[:1], tops[-1], *bbox[2:]))
    return crop.filter(keys_and_input_text).extract_text()


def can_we_process_pdf(filepath: str) -> bool:
    """Is this PDF extractable

    :param filepath: Location of the PDF
    :return: Whether it is digital document
    """
    with pdfplumber.open(filepath) as pdf:
        if len(pdf.pages[0].extract_text()) < 100:
            return False
        return True


def convert_pdf(filepath: str, temp_output: str, form: str) -> bool:
    """Find extract and merge forms into one page PDFs

    To simplify extraction we identify the pages in the larger pdf and
    convert them into a single page PDF.

    :param filepath: Location of the pdf to extract
    :param temp_output: temporary filepath
    :param form: Form to find
    :return: Did we succeed
    """
    pages = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            m = text[-300:].find(form)
            if m == -1:
                continue
            m = text[-300:].lower().find("page")
            if m == -1:
                continue
            pages.append(page.page_number)

    if len(pages) == 0:
        return False

    writer = PdfFileWriter()
    with open(filepath, "rb") as pdf_obj:
        pdf = PdfFileReader(pdf_obj)
        first = pages[0] - 1
        last = pages[-1] - 1
        if first == last:
            last = first + 1

        page = pdf.getPage(first)  # We pick the second page here
        h = page.mediaBox.getHeight()
        w = page.mediaBox.getWidth()

        t_page = PageObject.createBlankPage(None, w, h * (last - first + 1))
        length = last - first

        if length == 1:
            writer.addPage(page)
            with open(temp_output, "wb") as f:
                writer.write(f)
            return True

        for pg_number in range(first, last):
            page = pdf.getPage(pg_number)
            t_page.mergeScaledTranslatedPage(
                page2=page, scale=1, tx=0, ty=h * length, expand=False
            )
            length -= 1
            if not length:
                last_page = pdf.getPage(last)
                t_page.mergePage(last_page)
                writer.addPage(t_page)

        with open(temp_output, "wb") as f:
            writer.write(f)

    print(f"Converted {form}, with {1+last-first} pages, {first} to {last}")
    return True


# ------------ 106 E/F Document
def get_page_and_lines(
    filepath: str,
) -> Tuple[pdfplumber.pdf.Page, List[Dict]]:
    """Get first page and return the lines in the PDF

    :param filepath: Location of the PDF
    :return: PDF page and PDF lines
    """
    with pdfplumber.open(filepath) as pdf:
        only_page = pdf.pages[0]
        all_lines = pdf.pages[0].filter(line_filter).lines
    sorted_lines = sorted(all_lines, key=lambda x: x["top"])
    return only_page, sorted_lines


def parse_unsecured_creditors(
    page: pdfplumber.pdf.Page, top: int, bottom: int
) -> Dict:
    """Extract the information on the unsecured creditor section

    :param page: PDF page
    :param top: Y coordinate of the top of section
    :param bottom: Y coordinate of the bottom of section
    :return: Organized creditor data
    """
    data = []
    crop_one = page.crop((0, max(100, top - 500), page.width, bottom))
    crop = crop_one.crop((0, top, page.width, bottom))
    key = crop.filter(key_filter).extract_text().replace("\n", "")
    boxes = get_checkboxes(crop)
    lines = crop.filter(remove_margin_lines).lines
    for line in sorted(lines, key=lambda x: x["top"]):
        if not data and line["width"] > 20:
            continue
        output = crop_and_extract(crop_one, line, adjust=True, up=100)
        if data or (output is not None and key == output.replace("\n", "")):
            if (
                len(data) == 10
                and "2." in key
                or len(data) == 8
                and "4." in key
            ):
                continue
            data.append(output)
    if data:
        return make_creditor_dict(data, boxes, key)


def extract_other_creditors(
    page: pdfplumber.pdf.Page, start: Dict, stop: Dict
) -> Dict:
    """Process other creditors to be notified if any

    :param page:Page to crop
    :param start:Y coordinate of the top of the creditor section
    :param stop:Y coordinate of the bottom of the creditor section
    :return: The key, address and acct information
    """

    key_bbox = (start["x0"], start["top"] - 20, start["x1"], start["top"])
    addy_bbox = (0, start["top"] - 20, start["x0"] - 20, stop["top"])
    acct_bbox = (start["x1"] + 150, start["top"] + 20, page.width, stop["top"])

    key = page.crop(key_bbox).filter(just_text_filter).extract_text()
    address = page.crop(addy_bbox).filter(keys_and_input_text).extract_text()
    acct = page.crop(acct_bbox).filter(keys_and_input_text).extract_text()

    return {"address": address, "acct": acct, "key": key}


# 106 D
def parse_secured_creditors(
    only_page: pdfplumber.pdf.Page, top: int, bottom: int
) -> Dict:
    """Find and extract content from secured creditor portion of 106D

    :param only_page:PDF page
    :param top: Y coordinate for top of section
    :param bottom: Y coordinate of bottom of section
    :return: Organized data of the section
    """
    page = only_page.crop((0, max(100, top - 500), only_page.width, bottom))
    section = page.crop((0, top, only_page.width, bottom))
    key = section.filter(key_filter).extract_text()
    checkboxes = get_checkboxes(section)
    data = []
    lines = section.filter(remove_margin_lines).lines

    for line in sorted(lines, key=lambda x: x["top"]):
        x0, x1, top = line["x0"], line["x1"], int(line["top"])
        if not data and line["width"] > 20:
            continue
        page_crop = page.crop((x0, top - 200, x1, top))
        tops = [row["top"] for row in page_crop.lines if row["top"] != top]
        bbox = (line["x0"], tops[-1], line["x1"], line["top"])
        if len(tops) > 0:
            if len(data) == 6:
                page_crop = page.crop((x0, tops[-1] - 20, x1, top))
            elif len(data) == 8:
                page_crop = page.crop((x0, top - 50, x1, top))
            else:
                page_crop = page.crop(bbox)
        output = page_crop.filter(keys_and_input_text).extract_text()

        if data or key == output:
            data.append(output)

    if data and len(data) > 10:
        return make_secured_creditor_dict(data, checkboxes)


def get_checkboxes(crop: pdfplumber.pdf.Page) -> Dict:
    """Find and identify checked checkboxes

    Using multiple tolerances, find checkboxes and identify them by the content
    to the right of the checkbox.

    :param crop: Section of pdf to extract checkboxes from
    :return: Dictionary of selected checkboxes
    """
    results = {}
    for tolerance in [3, 5]:
        filtered_data = crop.filter(filter_boxes).extract_text(
            y_tolerance=tolerance
        )
        if "[]" not in filtered_data:
            "Checkboxes unreadable"
            return {}
        filtered_lines = filtered_data.splitlines()
        checkboxes = [x.replace("  ", " ") for x in filtered_lines if "[" in x]
        q1 = ["debtor"]
        q2 = ["community", "see instructions"]
        q3 = ["No", "Yes"]
        q4 = ["contingent", "unliquidated", "disputed"]
        q5 = [
            "domestic",
            "taxes",
            "death",
            "specify",
            "loans",
            "obligations",
            "pension",
            "including",
            "judgment",
            "statutory",
            "agreement",
        ]

        debtor = [
            box.split(" ", 1)[1].strip()
            for box in checkboxes
            if "√" in box and any(s in box.lower() for s in q1)
        ]
        community = [
            box.split(" ", 1)[1].strip()
            for box in checkboxes
            if "√" in box and any(s in box.lower() for s in q2)
        ]
        offset = [
            box.split(" ", 1)[1].strip()
            for box in checkboxes
            if "√" in box and any(s in box for s in q3)
        ]
        info = [
            box.split(" ", 1)[1].strip()
            for box in checkboxes
            if "√" in box and any(s in box.lower() for s in q4)
        ]
        claim_type = [
            box.split(" ", 1)[1].strip()
            for box in checkboxes
            if "√" in box and any(s in box.lower() for s in q5)
        ]

        property_values = [
            box.split(" ", 1)[1].strip()
            for box in checkboxes
            if "√" in box and any(s in box for s in property_options)
        ]
        property_values = [
            s
            for s in property_options
            if any(s in box for box in property_values)
        ]

        data = {
            "debtor": debtor,
            "community": community,
            "offset": offset,
            "info": info,
            "claim_type": claim_type,
            "property": property_values,
        }
        if not results:
            results = data
        else:
            data = [{k: v} for k, v in data.items() if v != []]
            results = {**results, **data}
        return results


def find_property_sections(
    only_page: pdfplumber.pdf.Page,
) -> Optional[Iterator[Tuple[Union[int, Any], int, Union[int, Any]]]]:
    """Find property sections to iterate over

    Find Sections with white font and identifiers for each section

    :param only_page: PDF page to crop
    :return: None or Iterable sections as top bottom and id
    """
    rows = only_page.filter(input_white_text_and_left_side).extract_words()
    rows = [
        {"top": int(row["top"]), "text": row["text"]}
        for row in rows
        if len(row["text"]) > 2
        and row["text"][0] in "P12345"
        and "." == row["text"][1]
    ]
    if len(rows) == 0:
        return None
    bottoms = [
        int(line["top"])
        for line in only_page.lines
        if line["top"] > rows[0]["top"] and line["width"] > 530
    ][: len(rows)]
    tops = [r["top"] for r in rows]
    keys = [r["text"] for r in rows]
    return zip(tops, bottoms, keys)


# 106 A/B collection
def get_1_to_2_from_a_b(only_page: pdfplumber.pdf.Page) -> List[Dict]:
    """Extract real estate, automobile, jet ski, boats etc, from A/B.

    :param only_page:The PDF page to extract from
    :return: Extracted content
    """
    property_content = []
    sections = find_property_sections(only_page)
    if not sections:
        return property_content

    for top, bottom, key in sections:
        bbox = (0, top, only_page.width, bottom)
        crop = only_page.crop(bbox)
        data = get_all_values_from_crop(crop.lines, only_page)

        if "1." in key:
            cd = make_property_dict(key, data)
            checkboxes = get_checkboxes(crop)
            if not checkboxes:
                cd["property_interest"] = "Checkbox unreadable"
                cd["debtor"] = "Checkbox unreadable"
            else:
                cd["property_interest"] = checkboxes["property"]
                cd["debtor"] = checkboxes["debtor"]
            property_content.append(cd)

        if "3." in key or "4." in key:
            if "3." in key:
                cd = make_car_dict(key, data)
            else:
                cd = make_other_dict(key, data)

            checkboxes = get_checkboxes(crop)
            if not checkboxes:
                cd["debtor"] = "Checkbox unreadable"
            else:
                cd["debtor"] = checkboxes["debtor"]
            property_content.append(cd)

    return property_content


def get_ab_debtors(rows: List) -> List:
    """Find debtor names to remove from processing

    :param rows: Form content as list of strings
    :return: Debtor names
    """

    debtors = [rows[1]]
    if "[" not in rows[2]:
        m = re.match(r"\d", rows[2][0])
        if not m:
            debtors.append(rows[2])
    return debtors


def clean_ab_data(data: List):
    """Clean data into string or list of strings

    :param data:
    :return:
    """
    matches = re.findall(r".*?\$[\d., $]+", " ".join(data), re.M)
    if matches:
        return matches
    return " ".join(data)


def get_3_to_8_form_a_b(
    page: pdfplumber.pdf.Page,
) -> Tuple[
    List[Union[Dict[str, Any], Dict[Optional[Any], str]]], list, Optional[dict]
]:
    """Parse sections 3 to 8 of 106 A/B property form

    :param page:The pdf page to parse
    :return:Organized property data in the document.
    """
    part = 0
    totals, section, key = None, None, None
    results, data, part_eight = [], [], []

    rows = page.filter(filter_106_ab_content).extract_text().splitlines()
    debtors = get_ab_debtors(rows)

    # Remove debtor rows from lines
    rows = [r for r in rows if r not in debtors]
    for debtor in debtors:
        rows = [r for r in rows if debtor not in r]

    for row in rows[1:]:
        p = re.match(r"Part \d:", row)
        if p:
            part += 1
            continue
        # Extract parts 3 to 7
        if part in [3, 4, 5, 6, 7]:
            m = re.match(r"^\d{1,2}\. ?|^5", row)
            if not m:
                data.append(row)
                continue
            if section == row:
                continue
            if "54. " in row:
                results.append({"54.": row.split(" ")[1]})
            if key:
                data = [d for d in data if "[" not in d]
                if data:
                    if key == "24." and data == ["2"]:
                        data = []
                        continue
                    results.append({key: clean_ab_data(data)})
                data = []
                section = row
            key = row

        if part == 8:
            # Part 8 is the section containing grand totals.
            part_eight.append(row)
            if "63. " in row:  # this is the final row of Part 8
                totals = make_ab_totals(part_eight)

    return results, debtors, totals


def get_all_values_from_crop(
    lines: List[Dict], page: pdfplumber.pdf.Page
) -> List:
    """Find all text inputs for each line in the pdf crop

    :param lines: Possible text inputs
    :param page: PDF to crop
    :return: Text input for each line
    """
    data = []
    for line in lines:
        if line["width"] < 10:
            continue
        output = crop_and_extract(page, line, adjust=True, up=100)
        data.append(output)
    return data

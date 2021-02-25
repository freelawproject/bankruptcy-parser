import logging
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List, Union

from bankruptcy.fields import form_106_sum_text_inputs, stats_ef
from bankruptcy.filters import filter_106_sum_boxes, filter_106_sum_lines
from bankruptcy.utils import (
    can_we_process_pdf,
    convert_pdf,
    crop_and_extract,
    extract_other_creditors_d,
    extract_other_creditors_ef,
    get_1_to_2_from_a_b,
    get_3_to_8_form_a_b,
    get_106_sum_pages,
    get_page_and_lines,
    parse_secured_creditors,
    parse_unsecured_creditors,
)


def extract_official_form_106_sum(filepath: str) -> Dict:
    """Extract content from Official Form 106 Sum

    :param filepath: Location of the bankruptcy document
    :return: Data and statistics in Form 106 Sum
    """

    pages = get_106_sum_pages(filepath)
    boxes, inputs = [], []

    if not pages:
        # Pages not found, most likely a scanned PDF document.
        logging.info("Pages not found, may not be a vector pdf")
        return {"error": "Failed to find document."}

    for page in pages:
        checkboxes = page.filter(filter_106_sum_boxes).extract_text()
        if checkboxes:
            boxes.extend(checkboxes.splitlines())

        for line in page.filter(filter_106_sum_lines).lines:
            output = crop_and_extract(page, line, adjust=True, left_shift=5)
            inputs.append(output)

    if not inputs:
        return {}

    # Remove blank inputs
    for item in [6, 7, 10, -1, -2]:
        inputs.pop(item)

    # Analyze Text Inputs
    text_inputs = dict(zip(form_106_sum_text_inputs, inputs))
    checkbox_inputs = {
        "7/11/13": "√" in boxes[2],
        "amended": "√" in boxes[0],
        "consumer_debts": "√" in boxes[3],
        "non_consumer_debts": "√" in boxes[4],
    }
    return {**text_inputs, **checkbox_inputs}


def extract_official_form_106_e_f(
    filepath: str,
) -> Union[Dict[str, str], Dict[str, Union[str, Dict[Any, str], List[dict]]]]:
    """Extract content from 106 EF

    :param filepath: Location of the pdf
    :return: Content of 106 E/F
    """
    section = 0
    results = {}
    creditors, stats, markers = [], [], []

    with NamedTemporaryFile(suffix=".pdf") as file:
        success = convert_pdf(filepath, file.name, "Official Form 106 E/F")
        if not success:
            return {"error": "Failed to find document."}

        page, lines = get_page_and_lines(file.name)

        results["debtor1"] = crop_and_extract(
            page, lines[0], adjust=True, up_shift=30
        )
        results["debtor2"] = crop_and_extract(
            page, lines[1], adjust=True, up_shift=30
        )
        for line in lines:
            if 498 < line["width"] < 510:
                section += 1

            # Final Section
            if section == 4:
                if line["width"] < 110:
                    output = crop_and_extract(page, line, up_shift=10)
                    stats.append(output)
                    if len(stats) == 10:
                        results["statistics"] = dict(zip(stats_ef, stats))

            # Other sections
            if section == 3:
                if 10 < line["width"] < 20 or line["width"] > 530:
                    markers.append(line)

                if len(markers) == 2:
                    creditors = extract_other_creditors_ef(
                        page,
                        start=markers[0],
                        stop=markers[1],
                        creditors=creditors,
                    )
                    markers = []

            # 1 & 2 Sections
            if line["x0"] < 50 and section in (1, 2):
                # The three marker lines follow these characteristics.
                if len(markers) == 0 and line["width"] > 20:
                    continue
                markers.append(line["top"])
                if len(markers) != 3:
                    continue
                markers.pop(1)

                creditor = parse_unsecured_creditors(
                    page,
                    top=markers.pop(0),
                    bottom=markers.pop(0),
                )
                creditors.append(creditor)

        results["creditors"] = creditors
        return results


def extract_official_form_106_d(
    filepath: str,
) -> Dict[str, Union[List[dict], str]]:
    """Extract content on secured creditors

    :param filepath: Location of the bankruptcy document
    :return: Secured creditor content
    """
    section = 0
    creditors, markers = [], []
    results = {}

    with NamedTemporaryFile(suffix=".pdf") as file:
        success = convert_pdf(filepath, file.name, "Official Form 106D")
        if not success:
            return {"error": "Failed to find document."}
        page, lines = get_page_and_lines(file.name)

    for line in sorted(lines, key=lambda x: x["top"]):
        # if line["width"] < 10:
        #     continue
        if 498 < line["width"] < 510:
            section += 1

        # Other sections
        if section == 2:
            if 5 < line["width"] < 120 or line["width"] > 530:
                markers.append(line)

            if line["width"] > 530:
                # Sometimes there are weird lines. Boxes are not lines
                if len(markers) > 4:
                    creditors = extract_other_creditors_d(
                        page, markers, creditors
                    )
                markers = []

        # Main Sections
        if line["x0"] < 50 and (section == 1):
            if len(markers) == 0:
                if line["width"] > 20:
                    continue
            markers.append(line["top"])
            if len(markers) != 3:
                continue
            markers.pop(1)
            creditor = parse_secured_creditors(
                page, top=markers.pop(0), bottom=markers.pop(0)
            )
            if creditor:
                creditors.append(creditor)

    results["creditors"] = creditors
    return results


def extract_official_form_106_a_b(filepath) -> Dict:
    """Extract property information from official form 106 A/B

    :param filepath:Location of the pdf
    :return: Content from A/B if any
    """
    with NamedTemporaryFile(suffix=".pdf") as file:
        success = convert_pdf(filepath, file.name, "Official Form 106A/B")
        if not success:
            return {"error": "Failed to find document."}

        page, _ = get_page_and_lines(file.name)
        cars_land_and_crafts = get_1_to_2_from_a_b(page)
        results, debtors, totals = get_3_to_8_form_a_b(page)
        return {
            "cars_land_and_crafts": cars_land_and_crafts,
            "debtors": debtors,
            "other_property": results,
            "totals": totals,
        }


def extract_all(filepath: str) -> Union[Dict, bool]:
    """Extract content for all available documents

    :param filepath: Location of the PDF to extract
    :return: Data from bankruptcy document
    """
    processable = can_we_process_pdf(filepath)
    if not processable:
        return False

    form_106_ef = extract_official_form_106_e_f(filepath)
    form_106_sum = extract_official_form_106_sum(filepath)
    form_106_ab = extract_official_form_106_a_b(filepath)
    form_106_d = extract_official_form_106_d(filepath)

    return {
        "info": {
            "debtor_1": form_106_ef["debtor1"],
            "debtor_2": form_106_ef["debtor1"],
        },
        "form_106_ab": form_106_ab,
        "form_106_d": form_106_d,
        "form_106_ef": form_106_ef,
        "form_106_sum": form_106_sum,
    }

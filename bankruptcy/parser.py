import logging
from tempfile import NamedTemporaryFile
from typing import Dict, List, Tuple, Union

from bankruptcy.fields import form_106_sum_text_inputs, stats_ef
from bankruptcy.filters import (
    filter_106_sum_boxes,
    filter_106_sum_lines,
    keys_and_input_text,
)
from bankruptcy.utils import (
    can_we_process_pdf,
    convert_pdf,
    crop_and_extract,
    extract_other_creditors,
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
            output = crop_and_extract(page, line, adjust=True, left=5)
            if output:
                inputs.append(output)

    if not inputs:
        return {}

    # Analyze Text Inputs
    text_inputs = dict(zip(form_106_sum_text_inputs, inputs))
    checkbox_inputs = {
        "7/11/13": True if "√" in boxes[2] else False,
        "amended": True if "√" in boxes[0] else False,
        "consumer_debts": True if "√" in boxes[3] else False,
        "non_consumer_debts": True if "√" in boxes[4] else False,
    }
    return {**text_inputs, **checkbox_inputs}


def extract_official_form_106_e_f(
    filepath: str,
) -> Tuple[
    Dict[str, Union[str, Dict[str, str], List[dict]]],
    Union[str, None],
    Union[str, None],
]:
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
            return {"error": "Failed to find document."}, None, None

        page, lines = get_page_and_lines(file.name)

        debtor1 = crop_and_extract(page, lines[0], adjust=True, up=30)
        debtor2 = crop_and_extract(page, lines[1], adjust=True, up=30)
        results["debtor1"] = debtor1
        results["debtor2"] = debtor2
        for line in lines:

            if line["width"] < 10:
                continue
            if 498 < line["width"] < 510:
                section += 1

            # Final Section
            if section == 4:
                if line["width"] > 110:
                    continue
                output = crop_and_extract(page, line, up=10)
                stats.append(output)
                if len(stats) == 10:
                    results["statistics"] = dict(zip(stats_ef, stats))

            # Other sections
            if section == 3:
                if 10 < line["width"] < 20 or line["width"] > 530:
                    markers.append(line)
                if len(markers) == 2:
                    other_creditor = extract_other_creditors(
                        page, start=markers[0], stop=markers[1]
                    )
                    for creditor in creditors:
                        if creditor["key"] == str(other_creditor["key"]):
                            o = creditor["other_creditors"]
                            o.append(other_creditor)
                            creditor["other_creditors"] = o
                    markers = []

            # 1 & 2 Sections
            if line["x0"] < 50 and (
                section == 1 or section == 2
            ):  # The three marker lines follow these characteristics,
                if len(markers) == 0:
                    if line["width"] > 20:
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
        return results, debtor1, debtor2


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
        if line["width"] < 10:
            continue
        if 498 < line["width"] < 510:
            section += 1

        # Other sections
        if section == 2:
            if line["width"] < 10:
                continue
            if 5 < line["width"] < 120 or line["width"] > 530:
                markers.append(line)

            if line["width"] > 530:
                if len(markers) != 3 or len(markers) != 5:
                    markers = []
                    continue
                adjust = 0 if len(markers) == 5 else 12
                addy_bbox = (
                    0,
                    markers[0]["top"],
                    int(markers[-1]["x1"]) * 0.35,
                    markers[-1]["top"],
                )
                key_bbox = (
                    markers[-3]["x0"],
                    markers[0]["top"] - adjust,
                    markers[-3]["x1"],
                    markers[-3]["top"],
                )
                acct_bbox = (
                    markers[1]["x0"],
                    markers[1]["top"] - adjust,
                    markers[1]["x1"],
                    markers[1]["top"],
                )

                address = (
                    page.crop(addy_bbox)
                    .filter(keys_and_input_text)
                    .extract_text()
                )
                key = (
                    page.crop(key_bbox)
                    .filter(keys_and_input_text)
                    .extract_text()
                    .strip()
                )
                acct = (
                    page.crop(acct_bbox)
                    .filter(keys_and_input_text)
                    .extract_text()
                )

                for creditor in creditors:
                    if creditor["key"] == str(key):
                        o = creditor["other_creditors"]
                        o.append(
                            {"key": key, "address": address, "acct": acct}
                        )
                        creditor["other_creditors"] = o
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

    form_106_ef, debtor1, debtor2 = extract_official_form_106_e_f(filepath)
    form_106_sum = extract_official_form_106_sum(filepath)
    form_106_ab = extract_official_form_106_a_b(filepath)
    form_106_d = extract_official_form_106_d(filepath)

    return {
        "info": {"debtor_1": debtor1, "debtor_2": debtor2},
        "form_106_ab": form_106_ab,
        "form_106_d": form_106_d,
        "form_106_ef": form_106_ef,
        "form_106_sum": form_106_sum,
    }

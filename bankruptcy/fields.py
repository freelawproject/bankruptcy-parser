import re
import string
from typing import Dict, List

property_options = [
    "Single-family home",
    "Duplex or multi-unit building",
    "Condominium or cooperative",
    "Manufactured or mobile home",
    "Land",
    "Investment property",
    "Timeshare",
    "Other",
]

form_106_sum_text_inputs = [
    "1a",
    "1b",
    "1c",
    "2",
    "3a",
    "3b",
    "3_total",
    "4",
    "5",
    "8",
    "9a",
    "9b",
    "9c",
    "9d",
    "9e",
    "9f",
    "9g",
]

stats_ef = [f"6{letter}" for letter in list(string.ascii_lowercase[:11])]


def make_property_dict(key: str, data: List) -> Dict:
    """Organize real estate data for the debtor in 106 A/B

    :param key: The ID for the property in the form
    :param data: Extracted content from real estate section
    :return: Organized property information
    """
    if len(data) == 10:
        property_id = data[9]
    else:
        property_id = ""
    return {
        "key": key,
        "address": data[0],
        "city": data[1],
        "state": data[2],
        "zip": data[3],
        "property_value": data[4],
        "your_property_value": data[5],
        "other": data[6],
        "ownership_interest": data[7],
        "county": data[8],
        "property_id": property_id,
    }


def make_car_dict(key: str, data: List[str]) -> Dict:
    """Organize car data for 106 A/B of the debtor

    :param key: The section id
    :param data: Content extract from car data section
    :return: Organized data for automobile of debtor
    """
    return {
        "key": key,
        "make": data[0],
        "model": data[1],
        "year": data[2],
        "mileage": data[3],
        "other_information": data[5],
        "property_value": data[6],
        "your_property_value": data[7],
    }


def make_other_dict(key: str, data: List) -> Dict:
    """Make dictionary of property data for 106 A/B

    :param key: The unique identifier
    :param data:Property data
    :return: Organized data for 106 A/B
    """
    return {
        "key": key,
        "make": data[0],
        "model": data[1],
        "year": data[2],
        "other": data[4],
        "property_value": data[5],
        "your_property_value": data[6],
    }


def make_ab_totals(part_eight: List[str]) -> Dict:
    """Convert part eight data into a dictionary of results

    :param part_eight: Text for the final section of 106 A/B
    :return: Organized asset data
    """
    part_eight = " ".join(part_eight) + " "
    matches = re.findall(r"\$(.*?) ", part_eight)

    return {
        "total_real_estate": matches[0],
        "total_vehicles": matches[1],
        "total_household": matches[2],
        "total_financial_assets": matches[3],
        "total_business": matches[4],
        "total_farm": matches[5],
        "total_other": matches[6],
        "total_personal": matches[7],
        "total_all": matches[9],
    }


def make_creditor_dict(data: List[str], boxes: Dict, key: str) -> Dict:
    """Make creditor dictionary for 106 E/F

    :param data: Extracted content from section
    :param boxes: Checkbox data
    :param key: ID for the section
    :return: Organized creditor information
    """
    if not data[-2]:
        data[-2] = ""
    if not data[-1]:
        data[-1] = ""

    results = {
        "key": data[0].replace("\n", ""),
        "name": data[1],
        "acct": data[2],
        "total": data[3],
        "date": data[-4],
        "address": data[-3],
        "claim_type_other": data[-2] + data[-1],
        "debtor": boxes.get("debtor", "Failed to extract"),
        "offset": boxes.get("offset", "Failed to extract"),
        "info": boxes.get("info", "Failed to extract"),
        "claim_type": boxes.get("claim_type", "Failed to extract"),
        "community": boxes.get("community", "Failed to extract"),
        "other_creditors": [],
    }
    if "2." in key:
        additional_results = {
            "non_priority_amount": data[-5],
            "priority_amount": data[-6],
        }

        results = {**results, **additional_results}
    return results


def make_secured_creditor_dict(data: List[str], checkboxes: Dict) -> Dict:
    """Make creditor dictionary for 106 D

    :param data: Extracted content from section
    :param checkboxes: ID for the section
    :return: Organized creditor information
    """
    return {
        "key": data[0],
        "claim": data[1],
        "collateral": data[2],
        "unsecured": data[3],
        "name": data[4],
        "property": data[6],
        "address": data[7],
        "claim_type_other": data[8],
        "date": data[9],
        "acct": data[11],
        "debtor": checkboxes["debtor"],
        "info": checkboxes["info"],
        "claim_type": checkboxes["claim_type"],
        "community": checkboxes["community"],
        "other_creditors": [],
    }

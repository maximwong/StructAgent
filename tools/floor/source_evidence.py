"""Normalize quoted engineering values, without restricting surrounding prose."""

import re


ARABIC = r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?"
CHINESE = r"[负正]?[零〇一二两三四五六七八九十百千万]+(?:点[零〇一二两三四五六七八九]+)?"
NUMBER = rf"(?:{ARABIC}|{CHINESE})"
LENGTH = r"(?:毫米|millimet(?:er|re)s?|mm|厘米|centimet(?:er|re)s?|cm|米|met(?:er|re)s?|m)(?![a-zA-Z0-9²^/])"
LOAD = r"(?:(?:kN|千牛(?:顿)?)\s*(?:/|per|每)\s*(?:m(?:²|2|\^2)|㎡|square\s*met(?:er|re)s?|平方米|平米)|kPa)"
PAIR = re.compile(rf"({NUMBER})\s*({LENGTH})?\s*(?:×|[xX*]|乘以?|by)\s*({NUMBER})\s*({LENGTH})", re.I)
DIGITS = dict(zip("零〇一二两三四五六七八九", (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))


def number_value(token):
    if re.fullmatch(ARABIC, token):
        return float(token.replace(",", ""))
    sign = -1 if token.startswith("负") else 1
    token = token.lstrip("负正")
    integer, _, decimal = token.partition("点")
    if all(c in DIGITS for c in integer):
        value = int("".join(str(DIGITS[c]) for c in integer))
    else:
        total, section, current = 0, 0, 0
        for char in integer:
            if char in DIGITS:
                current = DIGITS[char]
            elif char == "万":
                total += (section + current) * 10000
                section, current = 0, 0
            else:
                section += (current or 1) * {"十": 10, "百": 100, "千": 1000}[char]
                current = 0
        value = total + section + current
    if decimal:
        value += float("0." + "".join(str(DIGITS[c]) for c in decimal))
    return sign * value


def length_value(token, unit):
    unit = unit.lower()
    factor = 1 if unit in ("mm", "毫米") or unit.startswith("millimet") else (
        10 if unit in ("cm", "厘米") or unit.startswith("centimet") else 1000)
    return number_value(token) * factor


def quoted_value(field, quote, index):
    """The model selects a verbatim quote; local code alone converts its values."""
    if field in ("concrete", "steel"):
        prefix = "C" if field == "concrete" else "HRB"
        matches = list(re.finditer(rf"(?<![A-Za-z0-9]){prefix}\s*\d+(?!\d)", quote, re.I))
        if len(matches) != 1 or index != 0:
            raise ValueError("Quote must identify one material grade.")
        return re.sub(r"\s+", "", matches[0][0]).upper()
    if field.startswith("span_"):
        pairs = list(PAIR.finditer(quote))
        if pairs:
            if len(pairs) != 1 or index != (0 if field == "span_x" else 1):
                raise ValueError("Pair axis order must match the selected template.")
            pair = pairs[0]
            return length_value(pair[1], pair[2] or pair[4]) if index == 0 else length_value(pair[3], pair[4])
        matches = list(re.finditer(rf"({NUMBER})\s*({LENGTH})", quote, re.I))
        if len(matches) != 1 or index != 0:
            raise ValueError("Quote must identify one length with units.")
        return length_value(matches[0][1], matches[0][2])
    matches = list(re.finditer(rf"({NUMBER})\s*{LOAD}", quote, re.I))
    if not matches:
        matches = list(re.finditer(rf"每(?:平方米|平米)\s*({NUMBER})\s*千牛(?:顿)?", quote))
    if len(matches) != 1 or index != 0:
        raise ValueError("Quote must identify one live load with units.")
    return number_value(matches[0][1])

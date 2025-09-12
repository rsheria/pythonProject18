import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from utils.link_template import apply_links_template


def test_apply_links_template_basic():
    template = "[url={LINK_RG}]RG[/url] | [url={LINK_NF}]NF[/url]"
    links = {
        "rapidgator.net": ["https://rg/file"],
        "nitroflare.com": "https://nf/file",
    }
    result = apply_links_template(template, links)
    assert "https://rg/file" in result
    assert "https://nf/file" in result


def test_apply_links_template_missing():
    template = "{LINK_RG}-{LINK_KF}-{LINK_KEEP}"
    links = {"rapidgator.net": ["a"]}
    result = apply_links_template(template, links)
    assert result.strip() == "a"


def test_apply_links_template_multiple_parts():
    template = "Part {PART}: {LINK_RG}"
    links = {"rapidgator.net": ["a1", "a2"]}
    result = apply_links_template(template, links)
    lines = result.splitlines()
    assert lines[0] == "Part 1: a1"
    assert lines[1] == "Part 2: a2"
def test_apply_links_template_skip_missing_parts():
    template = "RG {PART}: {LINK_RG}\nNF {PART}: {LINK_NF}\nDDL {PART}: {LINK_DDL}"
    links = {
        "rapidgator.net": ["rg1", "rg2"],
        "nitroflare.com": ["nf1", "nf2"],
        "ddownload.com": ["ddl1"],
    }
    result = apply_links_template(template, links)
    lines = result.splitlines()
    assert "DDL 2:" not in lines
    assert lines[0] == "RG 1: rg1"
    assert lines[1] == "NF 1: nf1"
    assert lines[2] == "DDL 1: ddl1"
    assert lines[3] == "RG 2: rg2"
    assert lines[4] == "NF 2: nf2"


def test_apply_links_template_no_empty_links_or_separators():
    template = "[url={LINK_RG}]RG[/url] ‖ [url={LINK_NF}]NF[/url]"
    links = {"rapidgator.net": ["rg1"]}
    result = apply_links_template(template, links)
    assert "[url=]" not in result
    assert "‖‖" not in result
    assert result.strip() == "[url=rg1]RG[/url]"

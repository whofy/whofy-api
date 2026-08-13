"""Guards that data/companies/*.yml stays wired to each fetcher."""
import pytest

from listings.shared.companies import load_companies


@pytest.mark.parametrize("source,required_key", [
    ("greenhouse", "board_token"),
    ("lever", "slug"),
    ("ashby", "slug"),
    ("workday", "jobs_url"),
])
def test_source_yaml_loads_and_has_expected_shape(source, required_key):
    companies = load_companies(source)
    assert isinstance(companies, list)
    assert len(companies) > 0, f"{source}.yml is empty"
    for entry in companies:
        assert "name" in entry, f"{source} entry missing 'name': {entry}"
        assert required_key in entry, (
            f"{source} entry missing '{required_key}': {entry}"
        )


def test_load_companies_raises_on_unknown_source():
    with pytest.raises(FileNotFoundError):
        load_companies("nonexistent_source_xyz")


def test_greenhouse_fetcher_uses_yaml_backed_list():
    """Regression: fetcher's COMPANIES must come from the YAML loader."""
    from listings.greenhouse import fetcher

    assert fetcher.COMPANIES is load_companies("greenhouse")


def test_lever_fetcher_uses_yaml_backed_list():
    from listings.lever import fetcher

    assert fetcher.COMPANIES is load_companies("lever")


def test_ashby_fetcher_uses_yaml_backed_list():
    from listings.ashby import fetcher

    assert fetcher.COMPANIES is load_companies("ashby")


def test_workday_fetcher_uses_yaml_backed_list():
    from listings.scraping.workday import fetcher

    assert fetcher.COMPANIES is load_companies("workday")

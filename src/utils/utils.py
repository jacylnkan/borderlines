import pycountry


def format_country_name(country: pycountry.db.Country) -> str:
    """
    Format the country name for display in the selectbox, including the country flag.

    Args:
        country (ExistingCountries): A pycountry ExistingCountries object.

    Returns:
        str: Formatted string with country name and flag.
    """
    # A country may include a comma and be formatted as such:
    # Korea, Republic Of
    # Reformat to Republic Of Korea
    name_parts = country.name.split(", ")
    if len(name_parts) > 1:
        formatted_name = " ".join(reversed(name_parts))
    else:
        formatted_name = country.name

    return f"{formatted_name} {country.flag}"


def get_all_country_names() -> dict[str, str]:
    """Retrieve all countries and their corresponding alpha-2 codes.

    Returns:
        dict[str, str]: A dictionary mapping country alpha-2 codes to formatted country names.
    """
    countries = sorted(pycountry.countries, key=lambda country: country.name)
    return {country.alpha_2: format_country_name(country) for country in countries}

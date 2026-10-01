import pycountry


def format_country_name(country: pycountry.db.Country) -> str:
    """
    Format the country name for display in the selectbox, including the country flag.

    Args:
        country (pycountry.db.Country): A pycountry ExistingCountries object.

    Returns:
        str: Formatted string with country name and flag.
    """
    # Countries that include a comma in their name as well as one of the following words as the
    # last word must be reformatted. Examples:
    #   Korea, Republic of -> Republic Of Korea
    #   Virgin Islands, British -> British Virgin Islands
    # Otherwise, use only the first part of the name before the comma. Examples:
    #   Taiwan, Province of China -> Taiwan
    #   Bonaire, Sint Eustatius and Saba -> Bonaire
    keywords = ["of", "the", "British", "U.S."]

    name_parts = country.name.split(", ")
    if len(name_parts) > 1:
        original_last_word = country.name.split()[-1]
        if original_last_word in keywords:
            formatted_name = f"{name_parts[1]} {name_parts[0]}"
        else:
            formatted_name = name_parts[0]
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

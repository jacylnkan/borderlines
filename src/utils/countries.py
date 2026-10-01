import pycountry

from src.utils.geography import load_country_geometries


def format_country_name(country: pycountry.db.Country) -> str:
    """Build a readable country label with its flag for the sidebar dropdown.

    Args:
        country (pycountry.db.Country): Country record exposing ``name`` and ``flag``.

    Returns:
        str: Reformatted country name followed by a space and its flag emoji.
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
    """Retrieve countries supported by the map dataset and their alpha-2 codes.

    Intersect pycountry records with the keys returned by the cached geometry loader.
    Sort by the formatted display label so dictionary iteration matches dropdown order.
    Territories without a separately mapped geometry are omitted.

    Returns:
        dict[str, str]: ISO alpha-2 codes mapped to country labels including flag emojis,
        in ascending display-label order.

    Raises:
        FileNotFoundError: A required map-data file is missing. Other errors from
            ``load_country_geometries`` propagate to the caller.
    """
    geometries = load_country_geometries()
    countries = [country for country in pycountry.countries if country.alpha_2 in geometries]
    countries.sort(key=format_country_name)
    return {country.alpha_2: format_country_name(country) for country in countries}
